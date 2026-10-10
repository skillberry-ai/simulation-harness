"""Enum derivation: spec-declared enums are carried into the IR in code.

Before this, an element field had no enum slot at all and a top-level field kept
its enum only if two LLM calls (enrich, then schema) both transcribed it. The
seed stage then had nothing to validate against: tau2-retail seeded
`payment_history[].transaction_type = "charge"` against a spec that allows only
`payment` / `refund`.
"""

from __future__ import annotations

import json
from pathlib import Path

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.stages.analyze.identity import (
    DerivedEntity,
    derive_identity,
)
from simulation_harness.skills.generation.stages.analyze.sources import (
    collect_sources,
)

EXAMPLES = Path(__file__).resolve().parents[5] / "utils" / "test-client" / "examples"


def _entity(schemas: dict[str, dict], name: str) -> DerivedEntity:
    ident = derive_identity(schemas, synthetic=True)
    return next(e for e in ident.entities if e.name == name)


def _order(status: dict) -> dict:
    return {"properties": {"order_id": {"type": "string"}, "status": status}}


def test_top_level_enum_is_derived() -> None:
    entity = _entity(
        {"Order": _order({"type": "string", "enum": ["pending", "delivered"]})},
        "Order",
    )
    assert dict(entity.enums) == {"status": ("pending", "delivered")}


def test_enums_from_several_sources_are_unioned_in_first_seen_order() -> None:
    """A stored value valid in any declaring source must stay valid."""
    entity = _entity(
        {
            "get_order": _order({"type": "string", "enum": ["pending", "delivered"]}),
            "list_orders": _order({"type": "string", "enum": ["cancelled", "pending"]}),
        },
        "Order",
    )
    assert dict(entity.enums)["status"] == ("pending", "delivered", "cancelled")


def test_a_source_without_an_enum_does_not_erase_a_declared_one() -> None:
    """A loosely typed source (typically a request body) constrains nothing."""
    entity = _entity(
        {
            "get_order": _order({"type": "string", "enum": ["pending", "delivered"]}),
            "update_order": _order({"type": "string"}),
        },
        "Order",
    )
    assert dict(entity.enums)["status"] == ("pending", "delivered")


def test_a_nullable_enum_is_not_derived() -> None:
    """Stamping it would reject the null the spec allows."""
    entity = _entity(
        {
            "get_order": _order({"type": "string", "enum": ["pending"]}),
            "list_orders": _order(
                {"type": "string", "enum": ["pending"], "nullable": True}
            ),
        },
        "Order",
    )
    assert "status" not in dict(entity.enums)


def test_a_non_string_enum_is_not_derived() -> None:
    entity = _entity({"Order": _order({"type": "integer", "enum": [1, 2]})}, "Order")
    assert "status" not in dict(entity.enums)


def test_embedded_element_field_carries_its_enum() -> None:
    schemas: dict[str, dict] = {
        "Order": {
            "properties": {
                "order_id": {"type": "string"},
                "notes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["gift", "memo"]},
                            "text": {"type": "string"},
                        },
                    },
                },
            }
        }
    }
    shape = dict(_entity(schemas, "Order").elements)["notes"]
    assert shape.kind == "embedded"
    fields = {f.name: f for f in shape.fields}
    assert fields["kind"].enum == ("gift", "memo")
    assert fields["text"].enum is None


def test_element_field_enums_are_unioned_across_sources() -> None:
    def order(kinds: list[str]) -> dict:
        return {
            "properties": {
                "order_id": {"type": "string"},
                "notes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"kind": {"type": "string", "enum": kinds}},
                    },
                },
            }
        }

    schemas = {"get_order": order(["gift"]), "list_orders": order(["memo", "gift"])}
    shape = dict(_entity(schemas, "Order").elements)["notes"]
    assert {f.name: f.enum for f in shape.fields}["kind"] == ("gift", "memo")


def test_tau2_retail_payment_history_transaction_type_is_pinned() -> None:
    """The measured bug: seeded `"charge"` against `["payment", "refund"]`."""
    spec_dict = json.loads((EXAMPLES / "tau2_retail_openapi.json").read_text())
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
    ident = derive_identity(
        sources.identity, synthetic=sources.synthetic, deferred=sources.deferred
    )
    order = next(e for e in ident.entities if e.collection == "orders")
    shape = dict(order.elements)["payment_history"]
    fields = shape.fields if shape.kind == "embedded" else shape.link_fields
    assert {f.name: f.enum for f in fields}["transaction_type"] == ("payment", "refund")
