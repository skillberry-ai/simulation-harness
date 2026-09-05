"""The one test that closes the loop from the derived contract back to runtime.

Every other guard in this area checks one half: that the IR carries the derived
contract, or that ``enforce_contract`` stamps a schema. Neither notices if the
*runtime* stops reading what generation wrote — ``state/loader.py`` recovers the
pk map from ``schema.json`` on disk, not from the IR, so the two halves can drift
apart with every existing test still green.

This asserts the whole chain in one line: derived contract → ``enforce_contract``
→ ``infer_primary_keys`` → the same pk map. An unrelated edit to either end
breaks it here rather than at simulation start-up.
"""

from __future__ import annotations

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages.schema import enforce_contract
from simulation_harness.state.loader import infer_primary_keys


def _ir() -> SpecModel:
    """Two entities with unlike primary keys: a bare ``id`` and a ``<noun>_id``.

    Both shapes matter. ``infer_primary_keys`` has a fallback that guesses ``id``
    when no ``x-primary-key`` is stamped, so an entity keyed on ``id`` would pass
    this test even if the stamping silently stopped working; ``order_id`` cannot.
    """
    return SpecModel(
        api_name="Shop",
        slug="shop",
        entities=[
            Entity(
                name="Order",
                collection="orders",
                primary_key="order_id",
                fields=[Field(name="order_id", type="string", required=True)],
            ),
            Entity(
                name="Coupon",
                collection="coupons",
                primary_key="id",
                fields=[Field(name="id", type="string", required=True)],
            ),
        ],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["orders", "coupons"],
            pk_map={"orders": "order_id", "coupons": "id"},
        ),
    )


def _llm_schema() -> dict:
    """A schema as the LLM writes it: correct $refs, no ``x-primary-key`` yet."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "orders": {"type": "array", "items": {"$ref": "#/$defs/Order"}},
            "coupons": {"type": "array", "items": {"$ref": "#/$defs/Coupon"}},
        },
        "$defs": {
            "Order": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
            },
            "Coupon": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
            },
        },
    }


def test_enforced_schema_yields_the_derived_pk_map_at_runtime() -> None:
    ir = _ir()
    enforced = enforce_contract(_llm_schema(), ir)
    db: dict[str, list[dict]] = {
        collection: [] for collection in ir.store_metadata.collections
    }

    assert infer_primary_keys(enforced, db) == ir.store_metadata.pk_map
