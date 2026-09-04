"""Guards against ordering leaks in the identity rule.

The whole point of deriving identity in code is that the same spec yields the
same contract every time. These tests assert the derivation cannot depend on
dict insertion order, which is the one way a pure function can still drift.
"""

from __future__ import annotations

from simulation_harness.skills.generation.stages.analyze.identity import (
    derive_identity,
)

SCHEMAS: dict[str, dict] = {
    "get_user__response": {
        "properties": {"user_id": {"type": "string"}, "name": {"type": "string"}}
    },
    "Error": {"properties": {"message": {"type": "string"}}},
    "list_orders__response": {
        "properties": {"order_id": {"type": "string"}, "total": {"type": "number"}}
    },
    "Ambiguous": {
        "properties": {"a_id": {"type": "string"}, "b_id": {"type": "string"}}
    },
}


def test_derivation_is_insensitive_to_schema_map_order() -> None:
    forward = derive_identity(SCHEMAS, synthetic=True)
    reversed_map = dict(reversed(list(SCHEMAS.items())))
    assert derive_identity(reversed_map, synthetic=True) == forward


def test_derivation_is_insensitive_to_property_order() -> None:
    forward = derive_identity(SCHEMAS, synthetic=True)
    shuffled = {
        name: {
            **schema,
            "properties": dict(reversed(list(schema["properties"].items()))),
        }
        for name, schema in SCHEMAS.items()
    }
    assert derive_identity(shuffled, synthetic=True) == forward


def test_derivation_is_repeatable() -> None:
    assert derive_identity(SCHEMAS, synthetic=True) == derive_identity(
        SCHEMAS, synthetic=True
    )
