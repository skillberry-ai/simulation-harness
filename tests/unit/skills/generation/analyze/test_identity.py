"""Specification tests for the deterministic identity rule."""

from __future__ import annotations

import pytest

from simulation_harness.skills.generation.stages.analyze.identity import (
    camel,
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
