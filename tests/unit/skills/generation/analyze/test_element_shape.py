"""Element-shape derivation: the storage side of a container field.

Regression coverage for the two bugs found building this: a circular subset test
(a promoted element is absorbed into its own target, so it is trivially a subset
of it) and a denormalized grandparent attribute (tau2-retail's order line carries
`Product` fields, which are neither `Item` columns nor order-scoped).
"""

from __future__ import annotations

from simulation_harness.skills.generation.stages.analyze.identity import derive_identity


# `synthetic=True` throughout: these specs reach identity derivation as generated
# operation-id keys, not spec-declared type names, which is the path rule 4 (a sole
# `*_id`) applies on. It is also what makes an intermediate promotion visible in
# provenance, which the second-hop test below depends on.
def _shapes(entities: tuple, name: str) -> dict:
    entity = next(e for e in entities if e.name == name)
    return dict(entity.elements)


def test_scalar_element_is_pinned() -> None:
    """The field where the schema stage flip-flopped between `{}` and
    `{"type": "string"}` run to run."""
    schemas: dict[str, dict] = {
        "User": {
            "properties": {
                "user_id": {"type": "string"},
                "order_ids": {"type": "array", "items": {"type": "string"}},
            }
        }
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "User")["order_ids"]
    assert shape.kind == "scalar"
    assert shape.type == "string"


def test_undeclared_element_shape_stays_undecided() -> None:
    """`"items": {}` says nothing, so nothing downstream should constrain it."""
    schemas: dict[str, dict] = {
        "User": {
            "properties": {
                "user_id": {"type": "string"},
                "tags": {"type": "array", "items": {}},
            }
        }
    }
    ident = derive_identity(schemas, synthetic=True)
    assert "tags" not in _shapes(ident.entities, "User")


def test_element_without_own_identity_is_embedded() -> None:
    """A value object — no identifier of its own — is stored inline."""
    schemas: dict[str, dict] = {
        "Reservation": {
            "properties": {
                "reservation_id": {"type": "string"},
                "passengers": {
                    "type": "array",
                    "items": {
                        "properties": {
                            "first_name": {"type": "string"},
                            "dob": {"type": "string"},
                        }
                    },
                },
            }
        }
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Reservation")["passengers"]
    assert shape.kind == "embedded"
    assert [f.name for f in shape.fields] == ["dob", "first_name"]


def test_promoted_element_that_projects_its_target_stores_a_bare_id() -> None:
    """The element clustered into `items`, and every field it carries is one the
    target carries independently, so the parent stores identifiers only."""
    item_element: dict = {
        "properties": {
            "item_id": {"type": "string"},
            "price": {"type": "number"},
        }
    }
    schemas: dict[str, dict] = {
        "Item": {
            "properties": {"item_id": {"type": "string"}, "price": {"type": "number"}}
        },
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "items": {"type": "array", "items": item_element},
            }
        },
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Order")["items"]
    assert shape.kind == "reference"
    assert (shape.target_collection, shape.target_key) == ("items", "item_id")
    assert shape.link_fields == ()


def test_parent_scoped_element_fields_become_a_link_object() -> None:
    """`amount` is carried by nothing but this element, so it is order-scoped and
    has to survive beside the key.

    This is the case a naive subset test cannot see: promoting the element copies
    `amount` into the `payment_methods` cluster, so comparing the element against
    its target compares it with itself.
    """
    schemas: dict[str, dict] = {
        "PaymentMethod": {"properties": {"payment_method_id": {"type": "string"}}},
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "payment_history": {
                    "type": "array",
                    "items": {
                        "properties": {
                            "payment_method_id": {"type": "string"},
                            "amount": {"type": "number"},
                        }
                    },
                },
            }
        },
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Order")["payment_history"]
    assert shape.kind == "reference"
    assert shape.target_collection == "payment_methods"
    assert [f.name for f in shape.link_fields] == ["payment_method_id", "amount"]


def test_grandparent_attribute_is_a_second_hop_not_parent_scoped() -> None:
    """tau2-retail's flagship shape. The order line carries `name`, which belongs
    to the `Product` the item hangs off — not to `Item`, and not to the order. It
    is one hop further out, so the parent still stores a bare identifier."""
    variant: dict = {
        "properties": {"item_id": {"type": "string"}, "price": {"type": "number"}}
    }
    schemas: dict[str, dict] = {
        "Item": {
            "properties": {"item_id": {"type": "string"}, "price": {"type": "number"}}
        },
        "Product": {
            "properties": {
                "product_id": {"type": "string"},
                "name": {"type": "string"},
                "variants": {"type": "array", "items": variant},
            }
        },
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "properties": {
                            "item_id": {"type": "string"},
                            "price": {"type": "number"},
                            "name": {"type": "string"},
                        }
                    },
                },
            }
        },
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Order")["items"]
    assert shape.kind == "reference"
    assert shape.link_fields == (), (
        "`name` is a Product attribute reached through Product.variants, so it is "
        "neither an Item column nor order-scoped: the order stores a bare item_id"
    )


def test_a_coincidental_same_named_field_does_not_excuse_a_leftover() -> None:
    """The nesting test matters: an unrelated entity also having `name` must not
    make a genuinely parent-scoped `name` look like a second hop."""
    schemas: dict[str, dict] = {
        "Widget": {"properties": {"widget_id": {"type": "string"}}},
        "Person": {
            "properties": {"person_id": {"type": "string"}, "name": {"type": "string"}}
        },
        "Box": {
            "properties": {
                "box_id": {"type": "string"},
                "widgets": {
                    "type": "array",
                    "items": {
                        "properties": {
                            "widget_id": {"type": "string"},
                            "name": {"type": "string"},
                        }
                    },
                },
            }
        },
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Box")["widgets"]
    assert shape.kind == "reference"
    assert [f.name for f in shape.link_fields] == ["widget_id", "name"]


def test_element_shape_is_hashable_so_derived_entity_stays_hashable() -> None:
    """DerivedEntity is a frozen dataclass; embedding an unhashable model in it
    would silently revoke that."""
    schemas: dict[str, dict] = {
        "User": {
            "properties": {
                "user_id": {"type": "string"},
                "order_ids": {"type": "array", "items": {"type": "string"}},
            }
        }
    }
    ident = derive_identity(schemas, synthetic=True)
    assert hash(ident.entities[0])
