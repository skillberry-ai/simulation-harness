from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.skills.generation.ir import Entity, StoreMetadata
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages.analyze import extract as E

VALID = {
    "api_name": "Aha",
    "entities": [
        {
            "name": "Feature",
            "collection": "features",
            "primary_key": "id",
            "fields": [{"name": "id", "type": "string", "required": True}],
        }
    ],
    "store_metadata": {"collections": ["features"], "pk_map": {"features": "id"}},
}


async def test_extract_data_model_builds_model():
    with patch.object(E, "call_json", AsyncMock(return_value=VALID)):
        dm = await E.extract_data_model({}, slug="aha", llm=object(), retries=2)
    assert dm.api_name == "Aha"
    assert dm.entities[0].name == "Feature"
    assert dm.store_metadata.pk_map == {"features": "id"}


def test_validate_data_model_flags_undeclared_collection():
    dm = E.DataModel(
        api_name="x",
        entities=[
            Entity(name="F", collection="features", primary_key="id", fields=[])
        ],
        store_metadata=StoreMetadata(collections=["other"], pk_map={"other": "id"}),
    )
    errors = E.validate_data_model(dm)
    assert any("features" in e for e in errors)


async def test_extract_repairs_then_succeeds():
    # first payload omits store_metadata (shape error), second is valid
    bad = {"api_name": "Aha", "entities": []}
    seq = iter([bad, VALID])
    with patch.object(
        E, "call_json", AsyncMock(side_effect=lambda *a, **k: next(seq))
    ):
        dm = await E.extract_data_model({}, slug="aha", llm=object(), retries=1)
    assert dm.entities[0].name == "Feature"


async def test_extract_exhausts_retries_raises():
    bad = {"api_name": "Aha", "entities": []}  # missing store_metadata every time
    with patch.object(E, "call_json", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError) as exc:
            await E.extract_data_model({}, slug="aha", llm=object(), retries=1)
    assert exc.value.stage == "extract"
