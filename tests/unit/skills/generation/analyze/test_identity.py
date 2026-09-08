"""Specification tests for the deterministic identity rule."""

from __future__ import annotations

import pytest

from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages.analyze.identity import (
    _flatten_union,
    _nested_objects,
    _noun_is_stem,
    camel,
    derive_identity,
    identity_key,
    noun_for,
    pluralize,
    snake,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("OrderItem", "order_item"),
        ("order_item", "order_item"),
        ("User", "user"),
        ("HTTPRequest", "h_t_t_p_request"),
    ],
)
def test_snake(raw: str, expected: str) -> None:
    assert snake(raw) == expected


def test_camel() -> None:
    assert camel("payment_method") == "PaymentMethod"
    assert camel("user") == "User"


@pytest.mark.parametrize(
    ("noun", "expected"),
    [
        ("item", "items"),
        ("payment_method", "payment_methods"),
        ("category", "categories"),
        ("box", "boxes"),
        ("address", "addresses"),
        ("status", "statuses"),
        # Already plural: must NOT become "attachmentses" (see plan decision 1).
        ("attachments", "attachments"),
        ("objs_channel", "objs_channels"),
    ],
)
def test_pluralize(noun: str, expected: str) -> None:
    assert pluralize(noun) == expected


def test_identity_key_prefers_declared_annotation() -> None:
    schema: dict = {"x-primary-key": "sku", "properties": {"id": {}, "sku": {}}}
    assert identity_key("Product", schema, synthetic=False) == "sku"


def test_identity_key_matches_schema_name() -> None:
    schema: dict = {"properties": {"user_id": {}, "order_id": {}}}
    assert identity_key("Order", schema, synthetic=False) == "order_id"


def test_identity_key_name_match_prefers_longest_noun() -> None:
    # "order_item".endswith("item") is true, but order_item_id is the better
    # match. Longest-noun-first makes this independent of property order.
    schema: dict = {"properties": {"item_id": {}, "order_item_id": {}}}
    assert identity_key("OrderItem", schema, synthetic=False) == "order_item_id"


def test_identity_key_falls_back_to_bare_id() -> None:
    schema: dict = {"properties": {"id": {}, "restaurant_id": {}}}
    assert identity_key("Reservation", schema, synthetic=False) == "id"


def test_identity_key_sole_foreign_id_only_for_synthetic() -> None:
    schema: dict = {"properties": {"order_id": {}, "status": {}}}
    # A synthetic key is an operation id, so name-matching can never fire and
    # the sole *_id is the only signal there is.
    assert identity_key("get_order_details__response", schema, synthetic=True) == (
        "order_id"
    )
    # A *named* schema with a single foreign-looking id is genuinely ambiguous.
    assert identity_key("OrderSummary", schema, synthetic=False) is None


def test_identity_key_undecidable_cases() -> None:
    assert (
        identity_key("Error", {"properties": {"message": {}}}, synthetic=True) is None
    )
    assert identity_key("Loose", {"type": "string"}, synthetic=True) is None
    assert (
        identity_key("Two", {"properties": {"a_id": {}, "b_id": {}}}, synthetic=True)
        is None
    )


def test_noun_for_comes_from_the_key_not_the_name() -> None:
    assert noun_for("order_id", "get_order_details__response") == "order"
    assert noun_for("payment_method_id", "Whatever") == "payment_method"


def test_noun_for_bare_id_falls_back_to_the_schema_name() -> None:
    assert noun_for("id", "Restaurant") == "restaurant"


def test_identity_key_matches_plural_property_name_to_singular_key() -> None:
    """The new pluralize(noun) == own arm enables nested object promotion.

    A nested object under property name "items" (plural) with "item_id" key
    (singular) must be identifiable without requiring synthetic=True. This tests
    the arm directly rather than indirectly through derive_identity.
    """
    schema: dict = {
        "properties": {"item_id": {"type": "string"}, "qty": {"type": "integer"}}
    }
    assert identity_key("items", schema, synthetic=False) == "item_id"


def test_derive_identity_clusters_by_key_across_schema_names() -> None:
    schemas = {
        "get_order__response": {
            "properties": {"order_id": {"type": "string"}, "status": {"type": "string"}}
        },
        "cancel_order__response": {
            "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}}
        },
    }
    model = derive_identity(schemas, synthetic=True)
    assert model.collections == ["orders"]
    assert model.pk_map == {"orders": "order_id"}
    (order,) = model.entities
    assert order.name == "Order"
    # Fields are unioned across every schema in the cluster.
    assert [f[0] for f in order.fields] == ["order_id", "reason", "status"]
    assert order.sources == ("cancel_order__response", "get_order__response")


def test_derive_identity_bare_id_does_not_cluster_across_names() -> None:
    schemas = {
        "Reservation": {"properties": {"id": {"type": "string"}}},
        "Restaurant": {"properties": {"id": {"type": "string"}}},
    }
    model = derive_identity(schemas, synthetic=False)
    assert model.collections == ["reservations", "restaurants"]
    assert model.pk_map == {"reservations": "id", "restaurants": "id"}


def test_derive_identity_records_undecidable_schemas() -> None:
    schemas = {
        "Error": {"properties": {"message": {"type": "string"}}},
        "User": {"properties": {"user_id": {"type": "string"}}},
    }
    model = derive_identity(schemas, synthetic=False)
    assert model.collections == ["users"]
    assert model.undecidable == ("Error",)


def test_derive_identity_promotes_nested_object_with_its_own_key() -> None:
    schemas = {
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "qty": {"type": "integer"},
                        },
                    },
                },
            }
        }
    }
    model = derive_identity(schemas, synthetic=False)
    assert model.collections == ["items", "orders"]
    assert model.pk_map == {"items": "item_id", "orders": "order_id"}


def test_derive_identity_promotes_through_additional_properties() -> None:
    schemas = {
        "Catalog": {
            "properties": {
                "catalog_id": {"type": "string"},
                "products": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {"product_id": {"type": "string"}},
                    },
                },
            }
        }
    }
    model = derive_identity(schemas, synthetic=False)
    assert model.collections == ["catalogs", "products"]


def test_derive_identity_does_not_promote_nested_sharing_the_parent_key() -> None:
    schemas = {
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "echo": {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                },
            }
        }
    }
    model = derive_identity(schemas, synthetic=False)
    assert model.collections == ["orders"]


def test_derive_identity_captures_field_types() -> None:
    schemas = {
        "User": {
            "properties": {
                "user_id": {"type": "string"},
                "age": {"type": "integer"},
                "profile": {"properties": {"nickname": {"type": "string"}}},
                "untyped": {},
            }
        }
    }
    (user,) = derive_identity(schemas, synthetic=False).entities
    assert dict(user.fields) == {
        "age": "integer",
        "profile": "object",
        "untyped": "string",
        "user_id": "string",
    }


def test_named_schema_with_a_non_matching_sole_fk_stays_undecidable() -> None:
    """Over-merge guard, eager direction.

    `Address`'s only `*_id` is a foreign key. Rule 1.2 finds no name match, 1.3
    no bare `id`, and 1.4 does not apply to a *named* schema — so `Address` must
    land in `undecidable`, not be absorbed into `User`.
    """

    schemas = {
        "User": {"properties": {"user_id": {"type": "string"}}},
        "Address": {
            "properties": {
                "user_id": {"type": "string"},
                "street": {"type": "string"},
            }
        },
    }
    model = derive_identity(schemas, synthetic=False)
    assert model.collections == ["users"]
    assert model.undecidable == ("Address",)
    (user,) = model.entities
    assert "street" not in dict(user.fields)


def test_named_schema_with_a_matching_fk_still_clusters() -> None:
    """Over-merge guard, shy direction — the narrowing must not over-trigger.

    `OrderLine` carries both `order_line_id` and `order_id`. Rule 1.2's name
    match picks `order_line_id`, so this named schema is decided in code even
    though it also holds a foreign key.
    """

    schemas = {
        "Order": {"properties": {"order_id": {"type": "string"}}},
        "OrderLine": {
            "properties": {
                "order_line_id": {"type": "string"},
                "order_id": {"type": "string"},
                "qty": {"type": "integer"},
            }
        },
    }
    model = derive_identity(schemas, synthetic=False)
    assert model.undecidable == ()
    # Entities sort by NOUN, not by collection name: "order" < "order_line".
    assert model.collections == ["orders", "order_lines"]
    assert model.pk_map == {
        "orders": "order_id",
        "order_lines": "order_line_id",
    }


def test_synthetic_schema_with_a_sole_fk_resolves_to_that_entity() -> None:
    """THE regression guard for the synthetic carve-out. Do not delete.

    An inline response named for its *operation* (`get_order_details`) shares no
    noun with its own key. Rule 1.4 resolves it through its sole `order_id`, and
    rule 2 takes the noun from the key rather than the schema name — so it joins
    `orders` instead of creating an `order_detailses` collection or going to the
    LLM. Without the synthetic carve-out, tau2-retail's six collections collapse.
    """

    schemas = {
        "get_order": {"properties": {"order_id": {"type": "string"}}},
        "get_order_details": {
            "properties": {
                "order_id": {"type": "string"},
                "shipping": {"type": "string"},
            }
        },
    }
    model = derive_identity(schemas, synthetic=True)
    assert model.collections == ["orders"]
    assert model.undecidable == ()
    (order,) = model.entities
    assert order.name == "Order"
    assert order.primary_key == "order_id"
    assert "shipping" in dict(order.fields)
    assert order.sources == ("get_order", "get_order_details")


def test_nested_absorption_is_unaffected_by_the_synthetic_split() -> None:
    """Rule 5 still absorbs a nested object that shares the parent's key.

    This is tau2-retail's `variants`, reached through `additionalProperties`: it
    is keyed `item_id`, the same as its parent, so it must NOT promote — no
    `variants` collection appears. Confirms rule 1.4's named/synthetic split does
    not disturb nested resolution.
    """

    schemas: dict[str, dict] = {
        "get_product": {
            "properties": {
                "product_id": {"type": "string"},
                "variants": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "price": {"type": "number"},
                        },
                    },
                },
            }
        },
        "get_item": {
            "properties": {
                "item_id": {"type": "string"},
                "price": {"type": "number"},
            }
        },
    }
    model = derive_identity(schemas, synthetic=True)
    assert model.collections == ["items", "products"]
    assert "variants" not in model.collections


@pytest.mark.parametrize(
    ("singular", "plural"),
    [("Address", "Addresses"), ("Status", "Statuses"), ("Box", "Boxes")],
)
def test_two_nouns_pluralizing_alike_fail_as_an_identity_error(
    singular: str, plural: str
) -> None:
    """``pluralize`` is not injective, and the collision must fail here.

    An ``Address`` entity beside an ``Addresses`` wrapper is an ordinary spec
    shape. Both nouns pluralize to ``addresses``, so the two clusters claim one
    collection and ``pk_map`` — keyed by collection — loses a primary key.
    Downstream that surfaces as a duplicate entry in the schema's top-level
    ``required``, which jsonschema rejects, wasting every repair attempt before
    hard-failing under stage "schema".
    """
    schemas = {
        singular: {"properties": {"id": {"type": "string"}}},
        plural: {"properties": {"id": {"type": "string"}}},
    }
    with pytest.raises(GenerationStageError) as exc:
        derive_identity(schemas, synthetic=False)
    assert exc.value.stage == "identity"
    message = "; ".join(exc.value.errors)
    assert snake(singular) in message
    assert snake(plural) in message


def test_a_lone_already_plural_noun_is_not_a_collision() -> None:
    """The guard must not fire on the ordinary single-schema case.

    ``Addresses`` on its own pluralizes to itself, which is fine — only a *pair*
    of nouns landing on one collection is the defect.
    """
    model = derive_identity(
        {"Addresses": {"properties": {"id": {"type": "string"}}}}, synthetic=False
    )
    assert model.collections == ["addresses"]


def test_flatten_union_unions_properties_and_intersects_required() -> None:
    schema: dict = {
        "anyOf": [
            {
                "properties": {
                    "source": {"const": "credit_card"},
                    "id": {"type": "string"},
                    "brand": {"type": "string"},
                    "last_four": {"type": "string"},
                },
                "required": ["source", "id", "brand", "last_four"],
            },
            {
                "properties": {
                    "source": {"const": "gift_card"},
                    "id": {"type": "string"},
                    "balance": {"type": "number"},
                },
                "required": ["source", "id", "balance"],
            },
            {
                "properties": {
                    "source": {"const": "gift_card"},
                    "id": {"type": "string"},
                },
                "required": ["source", "id"],
            },
        ]
    }
    flat = _flatten_union(schema)
    assert flat is not None
    assert sorted(flat["properties"]) == [
        "balance",
        "brand",
        "id",
        "last_four",
        "source",
    ]
    assert flat["required"] == ["id", "source"]
    assert flat["type"] == "object"


def test_flatten_union_folds_differing_const_into_enum() -> None:
    """A plain dict.update() would keep only the last variant's const, so every
    generated row would claim to be whichever variant sorted last."""
    schema: dict = {
        "anyOf": [
            {"properties": {"source": {"const": "credit_card"}}},
            {"properties": {"source": {"const": "gift_card"}}},
        ]
    }
    flat = _flatten_union(schema)
    assert flat is not None
    assert flat["properties"]["source"] == {"enum": ["credit_card", "gift_card"]}


def test_flatten_union_keeps_a_shared_const_as_is() -> None:
    schema: dict = {
        "anyOf": [
            {"properties": {"kind": {"const": "only"}}},
            {"properties": {"kind": {"const": "only"}}},
        ]
    }
    flat = _flatten_union(schema)
    assert flat is not None
    assert flat["properties"]["kind"] == {"const": "only"}


def test_flatten_union_declines_a_non_object_variant() -> None:
    """anyOf: [{type: string}, ...] is not an entity union."""
    assert (
        _flatten_union({"anyOf": [{"type": "string"}, {"properties": {"id": {}}}]})
        is None
    )


def test_flatten_union_declines_a_plain_schema() -> None:
    assert _flatten_union({"properties": {"id": {}}}) is None


def test_flatten_union_reads_oneof_too() -> None:
    flat = _flatten_union(
        {"oneOf": [{"properties": {"a": {}}}, {"properties": {"b": {}}}]}
    )
    assert flat is not None
    assert sorted(flat["properties"]) == ["a", "b"]
    assert flat["required"] == []


def test_nested_objects_sees_through_a_union_map() -> None:
    """tau2-retail's get_user_details.payment_methods: a map whose values are an
    anyOf union. Before this, the union had no `properties` so the promotion pass
    never saw the entity at all."""
    prop: dict = {
        "type": "object",
        "additionalProperties": {
            "anyOf": [
                {
                    "properties": {
                        "source": {"const": "credit_card"},
                        "id": {"type": "string"},
                    }
                },
                {
                    "properties": {
                        "source": {"const": "gift_card"},
                        "balance": {"type": "number"},
                        "id": {"type": "string"},
                    }
                },
            ]
        },
    }
    targets = list(_nested_objects(prop))
    assert len(targets) == 1
    assert sorted(targets[0]["properties"]) == ["balance", "id", "source"]


def test_identity_key_decides_a_union_schema() -> None:
    schema: dict = {
        "anyOf": [
            {
                "properties": {
                    "source": {"const": "credit_card"},
                    "id": {"type": "string"},
                }
            },
            {
                "properties": {
                    "source": {"const": "gift_card"},
                    "id": {"type": "string"},
                }
            },
        ]
    }
    assert identity_key("payment_methods", schema, synthetic=True) == "id"


def test_identity_key_still_declines_a_scalar_union() -> None:
    assert (
        identity_key("thing", {"anyOf": [{"type": "string"}]}, synthetic=True) is None
    )


def test_identity_key_rejects_a_list_valued_candidate() -> None:
    """tau2-retail's Order.fulfillments carries `tracking_id` as an ARRAY of ids.
    Adopting it made a collection whose primary key is a list, which store.py
    then keys under the stringified list "['TRK-DEL-001']"."""
    schema: dict = {
        "properties": {
            "tracking_id": {"type": "array", "items": {"type": "string"}},
            "item_ids": {"type": "array", "items": {"type": "string"}},
        }
    }
    assert identity_key("fulfillments", schema, synthetic=True) is None


def test_identity_key_rejects_an_object_valued_bare_id() -> None:
    schema: dict = {"properties": {"id": {"type": "object", "properties": {"v": {}}}}}
    assert identity_key("Thing", schema, synthetic=False) is None


def test_identity_key_accepts_an_untyped_candidate() -> None:
    """Absent type is the common case in these specs and is not evidence of a
    problem, so it must stay acceptable."""
    assert (
        identity_key("Order", {"properties": {"order_id": {}}}, synthetic=True)
        == "order_id"
    )


def test_identity_key_honours_a_declared_key_without_the_scalar_filter() -> None:
    """An explicit but impossible x-primary-key must fail loudly in the schema
    stage, not be quietly downgraded to undecidable here."""
    schema: dict = {
        "x-primary-key": "tracking_id",
        "properties": {"tracking_id": {"type": "array"}},
    }
    assert identity_key("Tracking", schema, synthetic=False) == "tracking_id"


@pytest.mark.parametrize(
    ("noun", "holder", "expected"),
    [
        ("payment", "payment_history", True),
        ("payment_method", "payment_history", False),
        ("tracking", "fulfillments", False),
        ("item", "items", True),
        ("order_item", "order_items", True),
        ("item", "order_items", False),
    ],
)
def test_noun_is_stem(noun: str, holder: str, expected: bool) -> None:
    assert _noun_is_stem(noun, holder) is expected


def test_rule_four_declines_a_foreign_key_at_element_level() -> None:
    """tau2-retail: payment_method_id in a payment_history line item references a
    payment method; it is not the line item's identity."""
    element: dict = {
        "properties": {
            "payment_method_id": {"type": "string"},
            "amount": {"type": "number"},
            "transaction_type": {"type": "string"},
        }
    }
    assert identity_key("payment_history", element, synthetic=True, nested=True) is None


def test_rule_four_keeps_an_own_id_at_element_level() -> None:
    """tau2-airline: payment_id in a payment_history line item IS its identity.
    This is the regression guard for the airline contract."""
    element: dict = {
        "properties": {"payment_id": {"type": "string"}, "amount": {"type": "number"}}
    }
    assert (
        identity_key("payment_history", element, synthetic=True, nested=True)
        == "payment_id"
    )


def test_rule_four_is_unchanged_at_top_level() -> None:
    """A synthetic response whose sole *_id carries a different noun still adopts
    it: at top level that id is the only signal available."""
    schema: dict = {
        "properties": {"tracking_id": {"type": "string"}, "status": {"type": "string"}}
    }
    assert (
        identity_key("get_shipping_label__response", schema, synthetic=True)
        == "tracking_id"
    )
