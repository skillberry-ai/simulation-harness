from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import Entity, StoreMetadata
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages import analyze as A
from simulation_harness.skills.generation.stages.analyze.extract import DataModel

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Aha", "version": "1.0"},
    "paths": {
        "/features/{id}": {
            "get": {
                "operationId": "getFeature",
                "tags": ["Features"],
                "summary": "Get a feature",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


def _dm():
    return DataModel(
        api_name="Aha",
        entities=[
            Entity(name="Feature", collection="features", primary_key="id", fields=[])
        ],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


def test_extract_operations_pulls_stub_fields():
    ops = A.extract_operations(OpenAPISpec(SPEC))
    assert ops == [
        {
            "operation_id": "getFeature",
            "method": "GET",
            "path": "/features/{id}",
            "tag": "Features",
            "summary": "Get a feature",
        }
    ]


def test_extract_operations_uses_sanitized_ids():
    spec = OpenAPISpec(
        {
            "openapi": "3.0.0",
            "info": {"title": "Booking", "version": "1.0"},
            "paths": {
                "/accommodations/search": {
                    "post": {
                        "operationId": "/accommodations/search",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )
    ops = A.extract_operations(spec)
    assert [o["operation_id"] for o in ops] == ["accommodations_search"]
    # The IR id must match what the parser/MCP layer exposes as the tool name.
    assert ops[0]["operation_id"] == spec.operations[0].operation_id


async def test_analyze_orchestrates_extract_classify_merge():
    records = [
        {
            "operation_id": "getFeature",
            "entity": "Feature",
            "kind": "read",
            "patterns": ["crud"],
        }
    ]
    phases: list[str] = []
    with (
        patch.object(A, "extract_data_model", AsyncMock(return_value=_dm())),
        patch.object(A, "classify_batch", AsyncMock(return_value=records)),
    ):
        ir = await A.analyze(
            SPEC,
            "aha",
            extract_llm=object(),
            classify_llm=object(),
            retries=2,
            batch_cap=40,
            concurrency=5,
            progress_cb=phases.append,
        )
    assert ir.slug == "aha"
    assert ir.operations[0].kind.value == "read"
    assert ir.operations[0].path == "/features/{id}"
    assert ir.validate_consistency() == []
    assert "extracting_model" in phases
    assert any(p.startswith("classifying_ops") for p in phases)


async def test_analyze_raises_on_coverage_gap():
    with (
        patch.object(A, "extract_data_model", AsyncMock(return_value=_dm())),
        patch.object(
            A, "classify_batch", AsyncMock(return_value=[])
        ),  # classifies nothing
    ):
        with pytest.raises(GenerationStageError) as exc:
            await A.analyze(
                SPEC,
                "aha",
                extract_llm=object(),
                classify_llm=object(),
                retries=0,
                batch_cap=40,
                concurrency=5,
            )
    assert exc.value.stage == "classify"
