from unittest.mock import AsyncMock, patch

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    SpecModel,
    StoreMetadata,
)
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
