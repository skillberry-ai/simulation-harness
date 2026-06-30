import pytest
from unittest.mock import AsyncMock, patch

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages import scenarios as SC


def _ir() -> SpecModel:
    return SpecModel(
        api_name="Aha",
        slug="aha",
        entities=[
            Entity(
                name="Feature",
                collection="features",
                primary_key="id",
                fields=[Field(name="id", type="string", required=True)],
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


async def test_generate_scenarios_parses_and_drops_unknown_ops() -> None:
    payload = {
        "scenarios": [
            {
                "title": "Read a feature",
                "intent": "Fetch a feature by id.",
                "operations": ["getFeature", "ghostOp"],
            }
        ]
    }
    with patch.object(SC, "call_json", AsyncMock(return_value=payload)):
        result = await SC.generate_scenarios(_ir(), llm=object(), count=1, retries=2)
    assert len(result) == 1
    assert result[0].title == "Read a feature"
    assert result[0].operations == ["getFeature"]  # ghostOp dropped


async def test_generate_scenarios_raises_when_empty() -> None:
    with patch.object(SC, "call_json", AsyncMock(return_value={"scenarios": []})):
        with pytest.raises(GenerationStageError):
            await SC.generate_scenarios(_ir(), llm=object(), count=3, retries=0)
