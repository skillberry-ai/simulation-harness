import json

import pytest
from unittest.mock import AsyncMock, patch

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationEvidence,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages import behavior as B


def _ir() -> SpecModel:
    return SpecModel(
        api_name="Aha",
        slug="aha",
        entities=[
            Entity(
                name="Feature",
                collection="features",
                primary_key="id",
                fields=[
                    Field(name="id", type="string", required=True),
                    Field(name="price", type="integer"),
                ],
            )
        ],
        operations=[
            Operation(
                operation_id="getFeature",
                method="GET",
                path="/features/{id}",
                entity="Feature",
                kind=OperationKind.read,
            )
        ],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


WELL_FORMED = (
    "### Numeric Ranges and Ordering\n- price 10-100\n\n"
    "### Derivation Rules\n- total = sum of prices\n\n"
    "### On-Demand Generation Rules\n- deterministic price by id\n"
)


async def test_generate_behavior_returns_section() -> None:
    with patch.object(B, "call_text", AsyncMock(return_value=WELL_FORMED)):
        out = await B.generate_behavior(_ir(), llm=object(), retries=2)
    assert "### Derivation Rules" in out
    assert "total = sum of prices" in out


async def test_generate_behavior_rejects_missing_heading() -> None:
    bad = "### Numeric Ranges and Ordering\n- price 10-100\n"
    with patch.object(B, "call_text", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError):
            await B.generate_behavior(_ir(), llm=object(), retries=0)


def test_behavior_prompt_contains_required_headings() -> None:
    prompt = B._load_prompt()
    for heading in B.REQUIRED_HEADINGS:
        assert heading in prompt


def test_ops_summary_carries_description() -> None:
    ir = _ir()
    ir.evidence = {
        "getFeature": OperationEvidence(
            description="Returns a feature; total equals the sum of line prices."
        )
    }

    records = json.loads(B._ops_summary(ir))

    assert records[0]["description"] == (
        "Returns a feature; total equals the sum of line prices."
    )


def test_ops_summary_description_none_without_evidence_entry() -> None:
    records = json.loads(B._ops_summary(_ir()))
    assert records[0]["description"] is None


def test_behavior_prompt_declares_numeric_prose_authoritative() -> None:
    prompt = B._load_prompt()
    assert "are authoritative" in prompt
    assert "description" in prompt
