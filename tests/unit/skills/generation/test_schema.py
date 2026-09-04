from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages import schema as S

GOOD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"features": {"type": "array", "items": {"$ref": "#/$defs/Feature"}}},
    "$defs": {
        "Feature": {
            "type": "object",
            "additionalProperties": False,
            "x-primary-key": "id",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        }
    },
}


def _ir() -> SpecModel:
    return SpecModel(
        api_name="Aha",
        slug="aha",
        entities=[
            Entity(
                name="Feature",
                collection="features",
                primary_key="id",
                fields=[Field(name="id", type="string", required=True)],
            )
        ],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


def test_validate_schema_accepts_valid_schema() -> None:
    assert S.validate_schema(GOOD_SCHEMA) == []


def test_validate_schema_flags_invalid_schema() -> None:
    assert S.validate_schema({"type": "not-a-type"})


async def test_generate_schema_returns_validated_schema() -> None:
    with patch.object(
        S, "call_json", AsyncMock(return_value={"schema_json": GOOD_SCHEMA})
    ):
        schema = await S.generate_schema(_ir(), llm=object(), retries=2)
    assert schema == GOOD_SCHEMA


def _shop_ir() -> SpecModel:
    return SpecModel(
        api_name="Shop",
        slug="shop",
        entities=[
            Entity(
                name="Order",
                collection="orders",
                primary_key="order_id",
                fields=[Field(name="order_id", type="string", required=True)],
            )
        ],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["orders"], pk_map={"orders": "order_id"}
        ),
    )


def _order_schema() -> dict:
    return {
        "type": "object",
        "properties": {"orders": {"type": "array", "items": {"$ref": "#/$defs/Order"}}},
        "$defs": {
            "Order": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            }
        },
    }


def test_enforce_contract_sets_x_primary_key_on_the_def() -> None:
    schema = S.enforce_contract(_order_schema(), _shop_ir())
    # loader.py reads the pk off the $def, not off the collection property.
    assert schema["$defs"]["Order"]["x-primary-key"] == "order_id"


def test_enforce_contract_overwrites_a_wrong_x_primary_key() -> None:
    schema = _order_schema()
    schema["$defs"]["Order"]["x-primary-key"] = "id"
    assert (
        S.enforce_contract(schema, _shop_ir())["$defs"]["Order"]["x-primary-key"]
        == "order_id"
    )


def test_enforce_contract_adds_the_primary_key_to_required() -> None:
    schema = _order_schema()
    schema["$defs"]["Order"]["required"] = []
    assert S.enforce_contract(schema, _shop_ir())["$defs"]["Order"]["required"] == [
        "order_id"
    ]


def test_validate_schema_without_ir_only_checks_json_schema_validity() -> None:
    assert S.validate_schema(_order_schema()) == []
    assert S.validate_schema({"type": 5}) != []


def test_validate_schema_rejects_a_missing_collection() -> None:
    schema = _order_schema()
    del schema["properties"]["orders"]
    errors = S.validate_schema(schema, _shop_ir())
    assert any("orders" in e for e in errors)


def test_validate_schema_rejects_an_extra_collection() -> None:
    schema = _order_schema()
    schema["properties"]["ghosts"] = {"type": "array", "items": {"$ref": "#/$defs/G"}}
    schema["$defs"]["G"] = {"type": "object", "properties": {}}
    errors = S.validate_schema(schema, _shop_ir())
    assert any("ghosts" in e for e in errors)


def test_validate_schema_rejects_a_collection_without_a_defs_ref() -> None:
    schema = _order_schema()
    schema["properties"]["orders"] = {"type": "array", "items": {"type": "object"}}
    errors = S.validate_schema(schema, _shop_ir())
    # loader.py silently defaults to pk="id" in this case, which is exactly the
    # drift this validator exists to prevent.
    assert any("$ref" in e for e in errors)


def test_validate_schema_rejects_a_dangling_defs_ref() -> None:
    schema = _order_schema()
    del schema["$defs"]["Order"]
    errors = S.validate_schema(schema, _shop_ir())
    assert any("Order" in e for e in errors)


def test_validate_schema_rejects_a_primary_key_missing_from_the_def() -> None:
    schema = _order_schema()
    del schema["$defs"]["Order"]["properties"]["order_id"]
    errors = S.validate_schema(schema, _shop_ir())
    assert any("order_id" in e for e in errors)


async def test_generate_schema_enforces_the_contract_on_the_returned_schema() -> None:
    payload = {"schema_json": _order_schema()}
    with patch.object(S, "call_json", AsyncMock(return_value=payload)):
        schema = await S.generate_schema(_shop_ir(), object(), retries=0)
    assert schema["$defs"]["Order"]["x-primary-key"] == "order_id"


# --- Fix round 1 --------------------------------------------------------
# enforce_contract now runs before validate_schema on every repair attempt
# (force-before-reject), so it no longer gets the shielding
# Draft202012Validator.check_schema used to provide when validate_schema ran
# first. _resolve_def must therefore isinstance-guard every level itself.


def test_enforce_contract_does_not_crash_on_malformed_properties() -> None:
    schema = {"type": "object", "properties": "orders"}
    result = S.enforce_contract(schema, _shop_ir())
    # Nothing resolvable, but the top-level stamp (Fix 2) still lands.
    assert result["required"] == ["orders"]
    assert result["additionalProperties"] is False


def test_enforce_contract_does_not_crash_on_malformed_defs() -> None:
    schema = _order_schema()
    schema["$defs"] = []
    result = S.enforce_contract(schema, _shop_ir())
    assert result["required"] == ["orders"]


def test_validate_schema_rejects_malformed_properties_without_crashing() -> None:
    errors = S.validate_schema({"type": "object", "properties": "orders"}, _shop_ir())
    assert errors


def test_validate_schema_rejects_malformed_defs_without_crashing() -> None:
    schema = _order_schema()
    schema["$defs"] = []
    errors = S.validate_schema(schema, _shop_ir())
    assert errors


def test_validate_schema_rejects_a_bool_schema_without_crashing() -> None:
    # True/False are valid Draft 2020-12 schemas, so check_schema alone
    # doesn't reject them; validate_schema must guard schema itself too.
    errors = S.validate_schema(True, _shop_ir())  # type: ignore[arg-type]
    assert errors


async def test_generate_schema_raises_a_clean_repair_error_for_malformed_properties() -> (
    None
):
    # Reproduces the reviewer's measured live-path crash: call_json returns a
    # schema with 'properties' as a string. Before this fix, enforce_contract
    # raised AttributeError, which escaped validate() -> with_repair ->
    # guard_timeout uncaught. It must now surface as a normal repair failure.
    payload = {"schema_json": {"type": "object", "properties": "orders"}}
    with patch.object(S, "call_json", AsyncMock(return_value=payload)):
        with pytest.raises(GenerationStageError):
            await S.generate_schema(_shop_ir(), object(), retries=0)


def test_enforce_contract_stamps_top_level_required_and_additional_properties() -> None:
    # Fix 2: db.json's collection set is only checked because these land on
    # the schema that reaches the seed stage's own validate_schema_and_db.
    schema = S.enforce_contract(_order_schema(), _shop_ir())
    assert schema["required"] == ["orders"]
    assert schema["additionalProperties"] is False


def test_enforce_contract_overwrites_a_wrong_top_level_contract() -> None:
    schema = _order_schema()
    schema["required"] = ["ghosts"]
    schema["additionalProperties"] = True
    schema = S.enforce_contract(schema, _shop_ir())
    assert schema["required"] == ["orders"]
    assert schema["additionalProperties"] is False


def _shared_def_ir(*, same_pk: bool) -> SpecModel:
    archived_pk = "order_id" if same_pk else "archive_id"
    return SpecModel(
        api_name="Shop",
        slug="shop",
        entities=[
            Entity(
                name="Order",
                collection="orders",
                primary_key="order_id",
                fields=[Field(name="order_id", type="string", required=True)],
            ),
            Entity(
                name="ArchivedOrder",
                collection="archived_orders",
                primary_key=archived_pk,
                fields=[Field(name=archived_pk, type="string", required=True)],
            ),
        ],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["orders", "archived_orders"],
            pk_map={"orders": "order_id", "archived_orders": archived_pk},
        ),
    )


def _shared_def_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "orders": {"type": "array", "items": {"$ref": "#/$defs/Order"}},
            "archived_orders": {"type": "array", "items": {"$ref": "#/$defs/Order"}},
        },
        "$defs": {
            "Order": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "archive_id": {"type": "string"},
                },
                "required": ["order_id"],
            }
        },
    }


def test_validate_schema_rejects_a_shared_def_with_differing_primary_keys() -> None:
    errors = S.validate_schema(_shared_def_schema(), _shared_def_ir(same_pk=False))
    assert any("shared" in e for e in errors)


def test_validate_schema_accepts_a_shared_def_with_the_same_primary_key() -> None:
    errors = S.validate_schema(_shared_def_schema(), _shared_def_ir(same_pk=True))
    assert errors == []
