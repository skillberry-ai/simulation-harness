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
from simulation_harness.skills.generation.stages.schema import (
    enforce_contract,
    validate_schema,
)
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


def test_map_shape_is_stamped_onto_additional_properties() -> None:
    """A map's element subschema belongs on `additionalProperties`, not `items`."""
    schema = _schema("options")
    schema["$defs"]["Order"]["properties"]["options"] = {"type": "object"}
    ir = _ir(ElementShape(kind="scalar", container="map", type="string"), "options")
    out = enforce_contract(schema, ir)
    prop = _order_prop(out, "options")
    assert prop["additionalProperties"] == {"type": "string"}
    assert "items" not in prop


def test_map_container_is_not_stamped_onto_an_array_property() -> None:
    """Declared type has to match the container the shape came from, or the stamp
    would bury a real shape mismatch."""
    ir = _ir(ElementShape(kind="scalar", container="map", type="string"), "items")
    out = enforce_contract(_schema(), ir)
    assert _order_prop(out)["items"] == {}


def test_embedded_map_values_are_type_checked_by_the_seed_gate() -> None:
    """What the map stamp does buy: a wrong value type is caught. Note it does NOT
    catch a wholly invented value shape, since additionalProperties stays open and
    no element-level `required` is emitted."""
    schema = _schema("variants")
    schema["$defs"]["Order"]["properties"]["variants"] = {"type": "object"}
    shape = ElementShape(
        kind="embedded",
        container="map",
        fields=(ElementField(name="price", type="number"),),
    )
    stamped = enforce_contract(schema, _ir(shape, "variants"))
    good = {"orders": [{"order_id": "o1", "variants": {"v1": {"price": 25}}}]}
    bad = {"orders": [{"order_id": "o1", "variants": {"v1": {"price": "twenty-five"}}}]}
    extra = {"orders": [{"order_id": "o1", "variants": {"v1": {"colour": "blue"}}}]}
    assert validate_schema_and_db(stamped, good) == []
    assert validate_schema_and_db(stamped, bad)
    assert validate_schema_and_db(stamped, extra) == []


def test_required_element_fields_are_stamped() -> None:
    shape = ElementShape(
        kind="embedded",
        fields=(
            ElementField(name="item_id", type="string", required=True),
            ElementField(name="note", type="string"),
        ),
    )
    out = enforce_contract(_schema("lines"), _ir(shape, "lines"))
    items = _order_prop(out, "lines")["items"]
    assert items["required"] == ["item_id"]


def test_no_required_key_when_nothing_is_required() -> None:
    """An absent `required` list must not become an empty one — `"required": []`
    is legal but noise, and it reads as a claim that nothing is required."""
    shape = ElementShape(
        kind="embedded", fields=(ElementField(name="note", type="string"),)
    )
    out = enforce_contract(_schema("lines"), _ir(shape, "lines"))
    assert "required" not in _order_prop(out, "lines")["items"]


def test_link_object_required_fields_are_stamped() -> None:
    shape = ElementShape(
        kind="reference",
        target_collection="payment_methods",
        target_key="payment_method_id",
        link_fields=(
            ElementField(name="payment_method_id", type="string", required=True),
            ElementField(name="amount", type="number", required=True),
        ),
    )
    out = enforce_contract(_schema("payment_history"), _ir(shape, "payment_history"))
    items = _order_prop(out, "payment_history")["items"]
    assert items["required"] == ["payment_method_id", "amount"]


def test_required_turns_the_seed_gate_into_a_shape_check() -> None:
    """The case this exists for: retail seeded `products[].variants` as a flattened
    object matching neither the spec's variant nor the `items` row it duplicates,
    and it validated because only value *types* were pinned."""
    schema = _schema("variants")
    schema["$defs"]["Order"]["properties"]["variants"] = {"type": "object"}
    shape = ElementShape(
        kind="embedded",
        container="map",
        fields=(
            ElementField(name="item_id", type="string", required=True),
            ElementField(name="price", type="number", required=True),
        ),
    )
    stamped = enforce_contract(schema, _ir(shape, "variants"))
    flattened = {
        "orders": [
            {"order_id": "o1", "variants": {"v1": {"colour": "Blue", "price": 25}}}
        ]
    }
    conforming = {
        "orders": [
            {"order_id": "o1", "variants": {"v1": {"item_id": "v1", "price": 25}}}
        ]
    }
    errors = validate_schema_and_db(stamped, flattened)
    assert errors and "'item_id' is a required property" in errors[0]
    assert validate_schema_and_db(stamped, conforming) == []


def test_extra_element_fields_are_still_allowed() -> None:
    """`additionalProperties` stays open: storage may carry bookkeeping no response
    declares, and for a nested element there is no union across sources to make
    closing it safe."""
    shape = ElementShape(
        kind="embedded",
        fields=(ElementField(name="sku", type="string", required=True),),
    )
    stamped = enforce_contract(_schema("lines"), _ir(shape, "lines"))
    db = {"orders": [{"order_id": "o1", "lines": [{"sku": "s1", "internal_seq": 3}]}]}
    assert validate_schema_and_db(stamped, db) == []


def test_element_ref_records_the_local_field_when_it_differs() -> None:
    """An inlined element whose own key name differs from the target's pk."""
    shape = ElementShape(
        kind="embedded",
        container="array",
        fields=(ElementField(name="amount", type="number"),),
        local_key="payment_method_id",
        target_collection="payment_methods",
        target_key="id",
    )
    out = enforce_contract(_schema("payment_history"), _ir(shape, "payment_history"))
    assert _order_prop(out, "payment_history")["x-element-ref"] == {
        "collection": "payment_methods",
        "key": "id",
        "field": "payment_method_id",
    }


def test_element_ref_omits_field_when_the_names_coincide() -> None:
    """The pre-existing reference shape must keep its two-key annotation."""
    shape = ElementShape(
        kind="reference", target_collection="items", target_key="item_id"
    )
    out = enforce_contract(_schema(), _ir(shape))
    assert _order_prop(out)["x-element-ref"] == {
        "collection": "items",
        "key": "item_id",
    }


def test_validate_schema_rejects_a_list_valued_primary_key() -> None:
    """`validate_schema` returns [] early without an ir, so one must be passed."""
    schema: dict = {
        "type": "object",
        "properties": {
            "trackings": {"type": "array", "items": {"$ref": "#/$defs/Tracking"}}
        },
        "$defs": {
            "Tracking": {
                "type": "object",
                "properties": {
                    "tracking_id": {"type": "array", "items": {"type": "string"}}
                },
            }
        },
    }
    ir = SpecModel(
        api_name="shop",
        slug="shop",
        entities=[
            Entity(
                name="Tracking",
                collection="trackings",
                primary_key="tracking_id",
                fields=[Field(name="tracking_id", type="array")],
            )
        ],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["trackings"], pk_map={"trackings": "tracking_id"}
        ),
    )
    errors = validate_schema(schema, ir)
    assert any("tracking_id" in e and "scalar" in e for e in errors)
