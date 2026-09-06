"""`enforce_contract` stamps derived element shapes onto array `items`.

The point of stamping rather than prompting: the schema prompt is never given an
element shape, so `items` stays `{}` — which accepts anything — and the seed stage
is then free to populate an array in a shape no other stage agreed to. Once
`items` is pinned, the seed stage's existing `validate_schema_and_db` call rejects
the mismatch inside its own repair loop, with no seed-prompt change.
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


def _schema(array_prop: str = "items") -> dict:
    return {
        "type": "object",
        "properties": {
            "orders": {"type": "array", "items": {"$ref": "#/$defs/Order"}},
        },
        "$defs": {
            "Order": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "order_id": {"type": "string"},
                    array_prop: {"type": "array", "items": {}},
                },
            }
        },
    }


def _ir(element: ElementShape | None, field_name: str = "items") -> SpecModel:
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
                    Field(name=field_name, type="array", element=element),
                ],
            )
        ],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["orders"], pk_map={"orders": "order_id"}
        ),
    )


def _order_prop(schema: dict, name: str = "items") -> dict:
    prop = schema["$defs"]["Order"]["properties"][name]
    assert isinstance(prop, dict)
    return prop


def test_bare_id_reference_is_stamped_as_a_string_array() -> None:
    shape = ElementShape(
        kind="reference", target_collection="items", target_key="item_id"
    )
    out = enforce_contract(_schema(), _ir(shape))
    assert _order_prop(out)["items"] == {"type": "string"}
    assert _order_prop(out)["x-element-ref"] == {
        "collection": "items",
        "key": "item_id",
    }


def test_link_object_reference_keeps_its_parent_scoped_fields() -> None:
    shape = ElementShape(
        kind="reference",
        target_collection="payment_methods",
        target_key="payment_method_id",
        link_fields=(
            ElementField(name="payment_method_id", type="string"),
            ElementField(name="amount", type="number"),
        ),
    )
    out = enforce_contract(_schema("payment_history"), _ir(shape, "payment_history"))
    items = _order_prop(out, "payment_history")["items"]
    assert items["type"] == "object"
    assert items["properties"] == {
        "payment_method_id": {"type": "string"},
        "amount": {"type": "number"},
    }


def test_embedded_element_is_stamped_open() -> None:
    """Storage may carry bookkeeping fields no response declares, and for a
    nested element there is no union-across-sources to make strictness safe."""
    shape = ElementShape(
        kind="embedded", fields=(ElementField(name="dob", type="string"),)
    )
    out = enforce_contract(_schema("passengers"), _ir(shape, "passengers"))
    items = _order_prop(out, "passengers")["items"]
    assert items == {"type": "object", "properties": {"dob": {"type": "string"}}}
    assert "additionalProperties" not in items


def test_scalar_element_is_stamped() -> None:
    out = enforce_contract(_schema(), _ir(ElementShape(kind="scalar", type="string")))
    assert _order_prop(out)["items"] == {"type": "string"}


def test_undecided_element_leaves_items_untouched() -> None:
    """No declared element shape means no claim: `{}` stays `{}` rather than
    being guessed at."""
    out = enforce_contract(_schema(), _ir(None))
    assert _order_prop(out)["items"] == {}
    assert "x-element-ref" not in _order_prop(out)


def test_non_array_property_is_left_alone() -> None:
    """A wrong declared type is `validate_schema`'s to report; stamping `items`
    onto it would bury the real problem."""
    schema = _schema()
    schema["$defs"]["Order"]["properties"]["items"] = {"type": "string"}
    out = enforce_contract(schema, _ir(ElementShape(kind="scalar", type="string")))
    assert _order_prop(out) == {"type": "string"}


def test_stamped_items_makes_the_seed_gate_reject_a_wrong_element_shape() -> None:
    """The whole payoff: no seed-prompt change, the existing gate does the work."""
    shape = ElementShape(
        kind="reference", target_collection="items", target_key="item_id"
    )
    unstamped = _schema()
    stamped = enforce_contract(_schema(), _ir(shape))
    db = {"orders": [{"order_id": "o1", "items": [{"item_id": "i1", "name": "Tee"}]}]}

    # An empty `items` accepts anything: this is the defect being closed.
    assert validate_schema_and_db(unstamped, db) == []
    errors = validate_schema_and_db(stamped, db)
    assert errors and "is not of type 'string'" in errors[0]


def test_bare_ids_still_validate_once_stamped() -> None:
    shape = ElementShape(
        kind="reference", target_collection="items", target_key="item_id"
    )
    stamped = enforce_contract(_schema(), _ir(shape))
    db = {"orders": [{"order_id": "o1", "items": ["item_tee_classic_red_m"]}]}
    assert validate_schema_and_db(stamped, db) == []
