import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pydantic import SecretStr

from simulation_harness.skills.generation.ir import Entity, StoreMetadata
from simulation_harness.skills.generation.stages import analyze as A
from simulation_harness.skills.generation.stages import operations as O
from simulation_harness.skills.generation.stages import schema as SC
from simulation_harness.skills.generation.stages import scenarios as SCN
from simulation_harness.skills.generation.stages import seed as SD
from simulation_harness.skills.generation.stages.analyze.extract import DataModel
from simulation_harness.skills.generator import SkillGenerator

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Aha", "version": "1"},
    "paths": {
        "/features/{id}": {
            "get": {
                "operationId": "getFeature",
                "tags": ["Features"],
                "summary": "Get",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}
DATA_MODEL = DataModel(
    api_name="Aha",
    entities=[
        Entity(
            name="Feature",
            collection="features",
            primary_key="id",
            fields=[{"name": "id", "type": "string", "required": True}],
        )
    ],
    store_metadata=StoreMetadata(collections=["features"], pk_map={"features": "id"}),
)
CLASSIFY_RECORDS = [
    {
        "operation_id": "getFeature",
        "entity": "Feature",
        "kind": "read",
        "patterns": ["crud"],
    }
]
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"features": {"type": "array", "items": {"$ref": "#/$defs/Feature"}}},
    "$defs": {
        "Feature": {
            "type": "object",
            "additionalProperties": False,
            "x-primary-key": "id",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        }
    },
}


async def test_full_generation_writes_valid_bundle(tmp_path: Path):
    phases = []
    with (
        patch.object(A, "extract_data_model", AsyncMock(return_value=DATA_MODEL)),
        patch.object(A, "classify_batch", AsyncMock(return_value=CLASSIFY_RECORDS)),
        patch.object(SC, "call_json", AsyncMock(return_value={"schema_json": SCHEMA})),
        patch.object(
            SCN,
            "call_json",
            AsyncMock(
                return_value={
                    "scenarios": [
                        {
                            "title": "Get a feature",
                            "intent": "Fetch a feature by id.",
                            "operations": ["getFeature"],
                        }
                    ]
                }
            ),
        ),
        patch.object(
            SD,
            "call_json",
            AsyncMock(return_value={"db_json": {"features": [{"id": "f1"}]}}),
        ),
        patch.object(
            O,
            "call_text",
            AsyncMock(return_value="### /features/{id} GET\nReturns a feature."),
        ),
        patch("simulation_harness.skills.generation.pipeline.build_chat"),
    ):
        gen = SkillGenerator(api_key=SecretStr("k"))
        result = await gen.generate_skill(
            SPEC, "aha", tmp_path, progress_cb=phases.append
        )

    skill_dir = tmp_path / "aha"
    assert result == skill_dir / "SKILL.md"
    skill_md = (skill_dir / "SKILL.md").read_text()
    assert "name: aha" in skill_md
    assert "### /features/{id} GET" in skill_md
    assert "## Example Scenarios" in skill_md
    schema = json.loads((skill_dir / "schema.json").read_text())
    db = json.loads((skill_dir / "db.json").read_text())
    scenarios = json.loads((skill_dir / "scenarios.json").read_text())
    assert scenarios[0]["title"] == "Get a feature"
    import jsonschema

    jsonschema.validate(db, schema)
    assert "assembling" in phases


async def test_full_generation_disabled_scenarios(tmp_path: Path):
    from simulation_harness.config.models import GenerationConfig

    with (
        patch.object(A, "extract_data_model", AsyncMock(return_value=DATA_MODEL)),
        patch.object(A, "classify_batch", AsyncMock(return_value=CLASSIFY_RECORDS)),
        patch.object(SC, "call_json", AsyncMock(return_value={"schema_json": SCHEMA})),
        patch.object(SCN, "call_json", AsyncMock()) as mock_scen,
        patch.object(
            SD,
            "call_json",
            AsyncMock(return_value={"db_json": {"features": [{"id": "f1"}]}}),
        ),
        patch.object(
            O,
            "call_text",
            AsyncMock(return_value="### /features/{id} GET\nReturns a feature."),
        ),
        patch("simulation_harness.skills.generation.pipeline.build_chat"),
    ):
        gen = SkillGenerator(
            api_key=SecretStr("k"),
            generation_config=GenerationConfig(scenarios_enabled=False),
        )
        await gen.generate_skill(SPEC, "aha", tmp_path)

    mock_scen.assert_not_called()
    skill_dir = tmp_path / "aha"
    assert not (skill_dir / "scenarios.json").exists()
    assert "## Example Scenarios" not in (skill_dir / "SKILL.md").read_text()
