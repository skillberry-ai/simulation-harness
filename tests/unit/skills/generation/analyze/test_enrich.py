"""Tests for the enrich stage: field detail without contract authority."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages.analyze import enrich as E
from simulation_harness.skills.generation.stages.analyze.identity import (
    DerivedEntity,
    IdentityModel,
)

IDENTITY = IdentityModel(
    entities=(
        DerivedEntity(
            name="Order",
            collection="orders",
            primary_key="order_id",
            fields=(("order_id", "string"), ("status", "string")),
            sources=("get_order__response",),
        ),
    ),
    undecidable=(),
)

VALID = {
    "entities": [
        {
            "name": "Order",
            "collection": "orders",
            "primary_key": "order_id",
            "fields": [
                {"name": "order_id", "type": "string", "required": True},
                {
                    "name": "status",
                    "type": "string",
                    "required": True,
                    "enum": ["pending", "delivered"],
                    "description": "Fulfilment state.",
                },
            ],
            "relationships": [],
            "fingerprint_fields": ["status"],
            "temporal_fields": [],
        }
    ]
}


def test_structural_entities_is_a_usable_floor() -> None:
    entities = E.structural_entities(IDENTITY)
    assert len(entities) == 1
    order = entities[0]
    assert (order.name, order.collection, order.primary_key) == (
        "Order",
        "orders",
        "order_id",
    )
    assert [(f.name, f.type, f.required) for f in order.fields] == [
        ("order_id", "string", True),
        ("status", "string", False),
    ]


async def test_enrich_returns_entities_on_valid_payload() -> None:
    with patch.object(E, "call_json", AsyncMock(return_value=VALID)):
        entities = await E.enrich_entities(IDENTITY, {}, object(), retries=1)
    assert [e.name for e in entities] == ["Order"]
    status = next(f for f in entities[0].fields if f.name == "status")
    assert status.enum == ["pending", "delivered"]
    assert entities[0].fingerprint_fields == ["status"]


async def test_enrich_rejects_a_changed_collection() -> None:
    bad = {"entities": [{**VALID["entities"][0], "collection": "order_records"}]}
    with patch.object(E, "call_json", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError) as exc:
            await E.enrich_entities(IDENTITY, {}, object(), retries=0)
    assert exc.value.stage == "enrich"
    assert any("orders" in e for e in exc.value.errors)


async def test_enrich_rejects_a_changed_primary_key() -> None:
    bad = {"entities": [{**VALID["entities"][0], "primary_key": "id"}]}
    with patch.object(E, "call_json", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError):
            await E.enrich_entities(IDENTITY, {}, object(), retries=0)


async def test_enrich_rejects_an_invented_entity() -> None:
    bad = {
        "entities": [
            VALID["entities"][0],
            {
                "name": "Ghost",
                "collection": "ghosts",
                "primary_key": "ghost_id",
                "fields": [{"name": "ghost_id", "type": "string", "required": True}],
            },
        ]
    }
    with patch.object(E, "call_json", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError) as exc:
            await E.enrich_entities(IDENTITY, {}, object(), retries=0)
    assert any("Ghost" in e for e in exc.value.errors)


async def test_enrich_rejects_a_dropped_entity() -> None:
    with patch.object(E, "call_json", AsyncMock(return_value={"entities": []})):
        with pytest.raises(GenerationStageError) as exc:
            await E.enrich_entities(IDENTITY, {}, object(), retries=0)
    assert any("Order" in e for e in exc.value.errors)


async def test_enrich_requires_the_primary_key_among_the_fields() -> None:
    bad = {
        "entities": [
            {
                **VALID["entities"][0],
                "fields": [{"name": "status", "type": "string", "required": True}],
            }
        ]
    }
    with patch.object(E, "call_json", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError) as exc:
            await E.enrich_entities(IDENTITY, {}, object(), retries=0)
    assert any("order_id" in e for e in exc.value.errors)


async def test_enrich_repairs_after_a_bad_first_attempt() -> None:
    bad = {"entities": [{**VALID["entities"][0], "primary_key": "id"}]}
    call = AsyncMock(side_effect=[bad, VALID])
    with patch.object(E, "call_json", call):
        entities = await E.enrich_entities(IDENTITY, {}, object(), retries=1)
    assert [e.name for e in entities] == ["Order"]
    assert call.await_count == 2


async def test_enrich_rejects_a_non_object_payload() -> None:
    with patch.object(E, "call_json", AsyncMock(return_value=["nope"])):
        with pytest.raises(GenerationStageError):
            await E.enrich_entities(IDENTITY, {}, object(), retries=0)
