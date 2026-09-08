"""`_op_context` hands the operation stage the entities its arrays point at.

A `reference` element shape says the parent stores identifiers. Knowing that is
not enough to write a contract: projecting the response means knowing what the
target carries, and creating such an element means knowing where to insert it.
The stage is given only its own entity, so without this it can see that
`orders[].items` holds `items` identifiers and still not name a single field the
projection yields.
"""

from __future__ import annotations

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import (
    ElementField,
    ElementShape,
    Entity,
    Field,
    Operation,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages.operations import (
    _linked_entities,
    _op_context,
)


def _entity(name: str, collection: str, pk: str, fields: list[Field]) -> Entity:
    return Entity(name=name, collection=collection, primary_key=pk, fields=fields)


def _model(order_items: ElementShape | None) -> SpecModel:
    order = _entity(
        "Order",
        "orders",
        "order_id",
        [
            Field(name="order_id", type="string", required=True),
            Field(name="items", type="array", element=order_items),
        ],
    )
    item = _entity(
        "Item",
        "items",
        "item_id",
        [
            Field(name="item_id", type="string", required=True),
            Field(name="price", type="number"),
        ],
    )
    product = _entity(
        "Product",
        "products",
        "product_id",
        [
            Field(name="product_id", type="string", required=True),
            Field(name="name", type="string"),
        ],
    )
    return SpecModel(
        api_name="shop",
        slug="shop",
        entities=[order, item, product],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["orders", "items", "products"],
            pk_map={"orders": "order_id", "items": "item_id", "products": "product_id"},
        ),
    )


def _order_of(ir: SpecModel) -> Entity:
    return next(e for e in ir.entities if e.name == "Order")


def test_reference_target_is_offered_to_the_stage() -> None:
    ir = _model(
        ElementShape(kind="reference", target_collection="items", target_key="item_id")
    )
    linked = _linked_entities(ir, _order_of(ir))
    assert [e["collection"] for e in linked] == ["items"]
    assert [f["name"] for f in linked[0]["fields"]] == ["item_id", "price"]


def test_second_hop_collection_is_offered_too() -> None:
    """The response denormalizes a grandparent attribute onto the element, so the
    collection that actually holds it has to be nameable."""
    ir = _model(
        ElementShape(
            kind="reference",
            target_collection="items",
            target_key="item_id",
            hop_collections=("products",),
        )
    )
    assert [e["collection"] for e in _linked_entities(ir, _order_of(ir))] == [
        "items",
        "products",
    ]


def test_embedded_and_scalar_arrays_link_nothing() -> None:
    """Inline elements need no second read, so nothing is added to the prompt."""
    for shape in (
        ElementShape(
            kind="embedded", fields=(ElementField(name="dob", type="string"),)
        ),
        ElementShape(kind="scalar", type="string"),
        None,
    ):
        ir = _model(shape)
        assert _linked_entities(ir, _order_of(ir)) == []


def test_embedded_foreign_key_annotation_links_its_target() -> None:
    """An ``embedded`` element can carry a foreign-key annotation without being
    promoted to ``kind="reference"`` — e.g. ``Order.payment_history`` lines that
    point at ``payment_methods`` while staying inline. The stage still needs the
    target named, or it cannot document maintaining a payment method's balance
    on refund."""
    order = _entity(
        "Order",
        "orders",
        "order_id",
        [
            Field(name="order_id", type="string", required=True),
            Field(
                name="payment_history",
                type="array",
                element=ElementShape(
                    kind="embedded",
                    local_key="payment_method_id",
                    target_collection="payment_methods",
                    target_key="id",
                ),
            ),
        ],
    )
    payment_method = _entity(
        "PaymentMethod",
        "payment_methods",
        "id",
        [
            Field(name="id", type="string", required=True),
            Field(name="balance", type="number"),
        ],
    )
    ir = SpecModel(
        api_name="shop",
        slug="shop",
        entities=[order, payment_method],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["orders", "payment_methods"],
            pk_map={"orders": "order_id", "payment_methods": "id"},
        ),
    )
    linked = _linked_entities(ir, order)
    assert [e["collection"] for e in linked] == ["payment_methods"]


def test_an_entity_never_links_to_itself() -> None:
    """A self-referencing array would otherwise duplicate the whole entity into
    its own context."""
    self_ref = ElementShape(
        kind="reference", target_collection="orders", target_key="order_id"
    )
    ir = _model(self_ref)
    assert _linked_entities(ir, _order_of(ir)) == []


def test_op_context_carries_element_shape_and_links() -> None:
    ir = _model(
        ElementShape(
            kind="reference",
            target_collection="items",
            target_key="item_id",
            hop_collections=("products",),
        )
    )
    op = Operation(
        operation_id="get_order_details",
        method="POST",
        path="/get_order_details",
        kind=OperationKind.read,
        entity="Order",
    )
    ctx = _op_context(
        OpenAPISpec({"openapi": "3.1.0", "info": {}, "paths": {}}), ir, op
    )
    items = next(f for f in ctx["entity"]["fields"] if f["name"] == "items")
    assert items["element"]["kind"] == "reference"
    assert items["element"]["target_key"] == "item_id"
    assert {e["collection"] for e in ctx["linked_entities"]} == {"items", "products"}


def test_no_entity_links_nothing() -> None:
    ir = _model(None)
    assert _linked_entities(ir, None) == []
