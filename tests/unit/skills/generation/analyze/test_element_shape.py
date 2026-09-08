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


def test_foreign_key_element_stays_inline_with_a_reference_annotation() -> None:
    """tau2-retail's Order.payment_history. `payment_method_id` references a
    payment method rather than identifying the line item, so the element is
    stored inline and the reference is recorded as an annotation.

    This replaces an earlier test that asserted `kind == "reference"` here. That
    encoded the defect: adopting the foreign key coined a `payment_methods`
    collection out of payment-history line items.
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
    assert shape.kind == "embedded"
    assert [f.name for f in shape.fields] == ["amount", "payment_method_id"]
    assert shape.local_key == "payment_method_id"
    assert (shape.target_collection, shape.target_key) == (
        "payment_methods",
        "payment_method_id",
    )
    assert shape.link_fields == ()


def test_list_valued_foreign_key_gets_no_annotation() -> None:
    """Order.fulfillments' tracking_id is an array, so it can identify nothing and
    references nothing: plain inline data, and no `trackings` collection."""
    schemas: dict[str, dict] = {
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "fulfillments": {
                    "type": "array",
                    "items": {
                        "properties": {
                            "tracking_id": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "item_ids": {"type": "array", "items": {"type": "string"}},
                        }
                    },
                },
            }
        },
    }
    ident = derive_identity(schemas, synthetic=True)
    assert [e.collection for e in ident.entities] == ["orders"]
    shape = _shapes(ident.entities, "Order")["fulfillments"]
    assert shape.kind == "embedded"
    assert shape.local_key is None
    assert shape.target_collection is None


def test_a_back_reference_to_the_parent_is_not_annotated() -> None:
    """An order line carrying its parent's own `order_id` is a back-reference, and a
    back-reference is redundant: containment already states the parent link, so
    recording it as a reference annotation adds nothing.

    Suppressed at the source rather than downstream, because `x-element-ref` is
    stamped for any shape with a `target_collection` — leaving it set here would put
    a self-pointing reference into schema.json for a shape that already lives in
    `orders`.
    """
    schemas: dict[str, dict] = {
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "lines": {
                    "type": "array",
                    "items": {
                        "properties": {
                            "order_id": {"type": "string"},
                            "quantity": {"type": "integer"},
                        }
                    },
                },
            }
        },
    }
    ident = derive_identity(schemas, synthetic=True)
    assert [e.collection for e in ident.entities] == ["orders"]
    shape = _shapes(ident.entities, "Order")["lines"]
    assert shape.kind == "embedded"
    assert shape.local_key is None
    assert shape.target_collection is None


def test_own_id_element_still_becomes_a_reference() -> None:
    """The reference path must survive: Order.items/item_id name-matches, so it is
    still promoted and the parent stores bare identifiers."""
    schemas: dict[str, dict] = {
        "Item": {
            "properties": {"item_id": {"type": "string"}, "name": {"type": "string"}}
        },
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "properties": {
                            "item_id": {"type": "string"},
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
    assert (shape.target_collection, shape.target_key) == ("items", "item_id")


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


def test_second_hop_collection_is_recorded_not_just_excused() -> None:
    """The grandparent case again, from the other side: knowing the order stores a
    bare id is not enough — the response still needs `name`, so the collection
    that holds it is recorded where the hop is detected rather than left for a
    consumer to rediscover."""
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
    assert shape.link_fields == ()
    assert shape.hop_collections == ("products",)


def test_no_hop_is_recorded_for_a_pure_projection() -> None:
    schemas: dict[str, dict] = {
        "Item": {
            "properties": {"item_id": {"type": "string"}, "price": {"type": "number"}}
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
                        }
                    },
                },
            }
        },
    }
    ident = derive_identity(schemas, synthetic=True)
    assert _shapes(ident.entities, "Order")["items"].hop_collections == ()


def test_map_of_scalars_is_pinned() -> None:
    """`additionalProperties` maps were entirely unconstrained before: a map of
    option names to values reached schema.json as a bare `{"type": "object"}`."""
    schemas: dict[str, dict] = {
        "Item": {
            "properties": {
                "item_id": {"type": "string"},
                "options": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            }
        }
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Item")["options"]
    assert (shape.container, shape.kind, shape.type) == ("map", "scalar", "string")


def test_map_of_promoted_elements_stays_embedded_with_a_cross_reference() -> None:
    """A map is keyed by the referenced identifier already, so its keys carry the
    reference and its values stay an inline projection. Recording the target as an
    annotation keeps that visible without claiming the values are identifiers."""
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
                "variants": {"type": "object", "additionalProperties": variant},
            }
        },
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Product")["variants"]
    assert (shape.container, shape.kind) == ("map", "embedded")
    assert [f.name for f in shape.fields] == ["item_id", "price"]
    assert (shape.target_collection, shape.target_key) == ("items", "item_id")
    assert shape.link_fields == ()


def test_a_plain_nested_object_is_not_a_container() -> None:
    """An address is one value, not a collection of them, so it is out of scope and
    keeps whatever the schema prompt wrote."""
    schemas: dict[str, dict] = {
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "address": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            }
        }
    }
    ident = derive_identity(schemas, synthetic=True)
    assert "address" not in _shapes(ident.entities, "Order")


def test_element_required_is_captured() -> None:
    """`required` is what turns a type check into a shape check downstream."""
    schemas: dict[str, dict] = {
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "lines": {
                    "type": "array",
                    "items": {
                        "properties": {
                            "sku": {"type": "string"},
                            "note": {"type": "string"},
                        },
                        "required": ["sku"],
                    },
                },
            }
        }
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Order")["lines"]
    assert {(f.name, f.required) for f in shape.fields} == {
        ("sku", True),
        ("note", False),
    }


def test_no_declared_required_means_no_required() -> None:
    schemas: dict[str, dict] = {
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "lines": {
                    "type": "array",
                    "items": {"properties": {"sku": {"type": "string"}}},
                },
            }
        }
    }
    ident = derive_identity(schemas, synthetic=True)
    shape = _shapes(ident.entities, "Order")["lines"]
    assert [f.required for f in shape.fields] == [False]
