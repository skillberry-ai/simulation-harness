"""`enforce_contract` stamps spec-derived enums onto `schema.json`.

Stamped rather than prompted for the same reason as element shapes: the values
are known exactly from the spec, and once they are in the schema the seed
stage's existing `validate_schema_and_db` rejects an out-of-enum seed inside its
own repair loop.
"""

from __future__ import annotations

from simulation_harness.skills.generation.ir import (
    ElementField,
    ElementShape,
    Entity,
    Field,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages.schema import enforce_contract
from simulation_harness.skills.generation.stages.seed import validate_schema_and_db


def _schema(status_type: str = "string") -> dict:
    return {
        "type": "object",
        "properties": {
            "orders": {"type": "array", "items": {"$ref": "#/$defs/Order"}},
        },
        "$defs": {
            "Order": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "status": {"type": status_type},
                    "payment_history": {"type": "array", "items": {}},
                },
            }
        },
    }


def _ir(status_enum: list[str] | None) -> SpecModel:
    history = ElementShape(
        kind="embedded",
        container="array",
        fields=(
            ElementField(name="amount", type="number"),
            ElementField(
                name="transaction_type", type="string", enum=("payment", "refund")
            ),
        ),
    )
    return SpecModel(
        api_name="shop",
        slug="shop",
        entities=[
            Entity(
                name="Order",
                collection="orders",
                primary_key="order_id",
                fields=[
                    Field(name="order_id", type="string", required=True),
                    Field(name="status", type="string", enum=status_enum),
                    Field(name="payment_history", type="array", element=history),
                ],
            )
        ],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["orders"],
            pk_map={"orders": "order_id"},
            enum_map={"orders": {"status": status_enum}} if status_enum else {},
        ),
    )


def _order_def(schema: dict) -> dict:
    return schema["$defs"]["Order"]["properties"]


def test_top_level_enum_is_stamped() -> None:
    schema = enforce_contract(_schema(), _ir(["pending", "delivered"]))
    assert _order_def(schema)["status"]["enum"] == ["pending", "delivered"]


def test_derived_enum_replaces_whatever_the_llm_wrote() -> None:
    schema = _schema()
    _order_def(schema)["status"]["enum"] = ["pending", "invented"]
    schema = enforce_contract(schema, _ir(["pending", "delivered"]))
    assert _order_def(schema)["status"]["enum"] == ["pending", "delivered"]


def test_enum_is_not_stamped_onto_a_property_of_another_type() -> None:
    """A string enum on an integer property would be unsatisfiable; leave the
    type mismatch for `validate_schema` to report instead of burying it."""
    schema = enforce_contract(_schema(status_type="integer"), _ir(["pending"]))
    assert "enum" not in _order_def(schema)["status"]


def test_field_without_a_derived_enum_is_left_alone() -> None:
    """Only spec-derived enums are contract; an LLM's own enum is not forced."""
    schema = _schema()
    _order_def(schema)["status"]["enum"] = ["pending"]
    schema = enforce_contract(schema, _ir(None))
    assert _order_def(schema)["status"]["enum"] == ["pending"]


def test_element_field_enum_is_stamped_on_items() -> None:
    schema = enforce_contract(_schema(), _ir(None))
    items = _order_def(schema)["payment_history"]["items"]
    assert items["properties"]["transaction_type"] == {
        "type": "string",
        "enum": ["payment", "refund"],
    }
    assert items["properties"]["amount"] == {"type": "number"}


def test_out_of_enum_seed_is_rejected() -> None:
    """The measured tau2-retail failure, now caught by the seed gate."""
    schema = enforce_contract(_schema(), _ir(["pending", "delivered"]))
    db = {
        "orders": [
            {
                "order_id": "o1",
                "status": "pending",
                "payment_history": [{"amount": 10, "transaction_type": "charge"}],
            }
        ]
    }
    errors = validate_schema_and_db(schema, db)
    assert errors
    assert any("charge" in e for e in errors)
