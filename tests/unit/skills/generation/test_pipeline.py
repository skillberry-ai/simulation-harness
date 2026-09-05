from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.config.models import GenerationConfig
from simulation_harness.skills.generation import pipeline as P
from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.repair import GenerationStageError

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Aha", "version": "1"},
    "paths": {
        "/features/{id}": {
            "get": {
                "operationId": "getFeature",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}

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


async def test_run_pipeline_produces_bundle_with_scenarios() -> None:
    phases: list[Any] = []
    with (
        patch.object(P, "analyze", AsyncMock(return_value=_ir())),
        patch.object(P, "generate_schema", AsyncMock(return_value=SCHEMA)),
        patch.object(
            P,
            "generate_scenarios",
            AsyncMock(
                return_value=[
                    __import__(
                        "simulation_harness.skills.generation.ir",
                        fromlist=["Scenario"],
                    ).Scenario(
                        title="Read",
                        intent="Read a feature.",
                        operations=["getFeature"],
                    )
                ]
            ),
        ),
        patch.object(
            P,
            "generate_behavior",
            AsyncMock(return_value="### Derivation Rules\n- total = sum of prices"),
        ),
        patch.object(
            P, "generate_seed", AsyncMock(return_value={"features": [{"id": "f1"}]})
        ),
        patch.object(
            P, "generate_section", AsyncMock(return_value="### /features/{id} GET\nok")
        ),
        patch.object(P, "build_chat"),
    ):
        bundle = await P.run_pipeline(
            SPEC,
            "aha",
            api_key=None,
            base_url=None,
            gen_config=GenerationConfig(),
            model="m",
            progress_cb=phases.append,
        )
    assert bundle.schema == SCHEMA
    assert bundle.db == {"features": [{"id": "f1"}]}
    assert bundle.scenarios == [
        {"title": "Read", "intent": "Read a feature.", "operations": ["getFeature"]}
    ]
    assert "## Example Scenarios" in bundle.skill_md
    assert "designing_schema" in phases
    assert "imagining_scenarios" in phases
    assert "seeding_database" in phases
    assert "assembling" in phases
    assert "describing_behavior" in phases
    assert "### Derivation Rules" in bundle.skill_md


async def test_run_pipeline_disabled_scenarios_skips_stage() -> None:
    phases: list[Any] = []
    with (
        patch.object(P, "analyze", AsyncMock(return_value=_ir())),
        patch.object(P, "generate_schema", AsyncMock(return_value=SCHEMA)),
        patch.object(P, "generate_scenarios", AsyncMock()) as mock_scen,
        patch.object(
            P,
            "generate_behavior",
            AsyncMock(return_value="### Derivation Rules\n- total = sum of prices"),
        ),
        patch.object(
            P, "generate_seed", AsyncMock(return_value={"features": [{"id": "f1"}]})
        ),
        patch.object(
            P, "generate_section", AsyncMock(return_value="### /features/{id} GET\nok")
        ),
        patch.object(P, "build_chat"),
    ):
        bundle = await P.run_pipeline(
            SPEC,
            "aha",
            api_key=None,
            base_url=None,
            gen_config=GenerationConfig(scenarios_enabled=False),
            model="m",
            progress_cb=phases.append,
        )
    mock_scen.assert_not_called()
    assert bundle.scenarios == []
    assert "## Example Scenarios" not in bundle.skill_md
    assert "imagining_scenarios" not in phases


async def test_run_pipeline_disabled_behavior_skips_stage() -> None:
    phases: list[Any] = []
    with (
        patch.object(P, "analyze", AsyncMock(return_value=_ir())),
        patch.object(P, "generate_schema", AsyncMock(return_value=SCHEMA)),
        patch.object(P, "generate_scenarios", AsyncMock(return_value=[])),
        patch.object(P, "generate_behavior", AsyncMock()) as mock_behavior,
        patch.object(
            P, "generate_seed", AsyncMock(return_value={"features": [{"id": "f1"}]})
        ),
        patch.object(
            P, "generate_section", AsyncMock(return_value="### /features/{id} GET\nok")
        ),
        patch.object(P, "build_chat"),
    ):
        bundle = await P.run_pipeline(
            SPEC,
            "aha",
            api_key=None,
            base_url=None,
            gen_config=GenerationConfig(behavior_enabled=False),
            model="m",
            progress_cb=phases.append,
        )
    mock_behavior.assert_not_called()
    assert "describing_behavior" not in phases
    assert "### Derivation Rules" not in bundle.skill_md


async def test_run_pipeline_behavior_stage_failure_skips_gracefully() -> None:
    phases: list[Any] = []
    with (
        patch.object(P, "analyze", AsyncMock(return_value=_ir())),
        patch.object(P, "generate_schema", AsyncMock(return_value=SCHEMA)),
        patch.object(P, "generate_scenarios", AsyncMock(return_value=[])),
        patch.object(
            P,
            "generate_behavior",
            AsyncMock(side_effect=GenerationStageError("behavior", ["boom"])),
        ),
        patch.object(
            P, "generate_seed", AsyncMock(return_value={"features": [{"id": "f1"}]})
        ),
        patch.object(
            P, "generate_section", AsyncMock(return_value="### /features/{id} GET\nok")
        ),
        patch.object(P, "build_chat"),
    ):
        bundle = await P.run_pipeline(
            SPEC,
            "aha",
            api_key=None,
            base_url=None,
            gen_config=GenerationConfig(),
            model="m",
            progress_cb=phases.append,
        )
    assert "### Derivation Rules" not in bundle.skill_md
    assert any(p.startswith("behavior_skipped") for p in phases)
    assert "assembling" in phases


async def test_run_pipeline_behavior_failure_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The degrade to the static preamble must leave a trace in logs/.

    Carrying descriptions into this stage raises its timeout probability, and a
    progress callback alone is invisible after the run.
    """
    import logging

    caplog.set_level(logging.WARNING)
    with (
        patch.object(P, "analyze", AsyncMock(return_value=_ir())),
        patch.object(P, "generate_schema", AsyncMock(return_value=SCHEMA)),
        patch.object(P, "generate_scenarios", AsyncMock(return_value=[])),
        patch.object(
            P,
            "generate_behavior",
            AsyncMock(side_effect=GenerationStageError("behavior", ["boom"])),
        ),
        patch.object(
            P, "generate_seed", AsyncMock(return_value={"features": [{"id": "f1"}]})
        ),
        patch.object(
            P, "generate_section", AsyncMock(return_value="### /features/{id} GET\nok")
        ),
        patch.object(P, "build_chat"),
    ):
        await P.run_pipeline(
            SPEC,
            "aha",
            api_key=None,
            base_url=None,
            gen_config=GenerationConfig(),
            model="m",
        )

    assert any(
        "behavior stage skipped" in message and "GenerationStageError" in message
        for message in caplog.messages
    )


async def test_run_pipeline_scenarios_failure_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The degrade to no scenarios must leave a trace in logs/.

    A progress callback alone is invisible after the run.
    """
    import logging

    caplog.set_level(logging.WARNING)
    with (
        patch.object(P, "analyze", AsyncMock(return_value=_ir())),
        patch.object(P, "generate_schema", AsyncMock(return_value=SCHEMA)),
        patch.object(
            P,
            "generate_scenarios",
            AsyncMock(side_effect=GenerationStageError("scenarios", ["boom"])),
        ),
        patch.object(
            P,
            "generate_behavior",
            AsyncMock(return_value="### Derivation Rules\n- total = sum of prices"),
        ),
        patch.object(
            P, "generate_seed", AsyncMock(return_value={"features": [{"id": "f1"}]})
        ),
        patch.object(
            P, "generate_section", AsyncMock(return_value="### /features/{id} GET\nok")
        ),
        patch.object(P, "build_chat"),
    ):
        await P.run_pipeline(
            SPEC,
            "aha",
            api_key=None,
            base_url=None,
            gen_config=GenerationConfig(),
            model="m",
        )

    assert any(
        "scenarios stage skipped" in message and "GenerationStageError" in message
        for message in caplog.messages
    )


def test_skill_bundle_carries_identity_provenance() -> None:
    bundle = P.SkillBundle(
        skill_md="x",
        schema={},
        db={},
        identity_provenance={"Order": "derived"},
    )
    assert bundle.identity_provenance == {"Order": "derived"}


def test_skill_bundle_identity_provenance_defaults_to_empty() -> None:
    assert P.SkillBundle(skill_md="x", schema={}, db={}).identity_provenance == {}
