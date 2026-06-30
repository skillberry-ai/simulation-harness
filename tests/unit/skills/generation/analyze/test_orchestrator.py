from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import Entity, StoreMetadata
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages import analyze as A
from simulation_harness.skills.generation.stages.analyze.extract import DataModel
from typing import Any

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

# RPC / tool-style spec: no components.schemas; data shapes live inline in
# request/response bodies (the tau2-airline shape).
RPC_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Booker", "version": "1.0"},
    "paths": {
        "/get_user": {
            "post": {
                "operationId": "get_user",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "returns": {
                                            "type": "object",
                                            "properties": {
                                                "user_id": {"type": "string"},
                                                "name": {"type": "string"},
                                            },
                                        }
                                    },
                                }
                            }
                        }
                    }
                },
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"user_id": {"type": "string"}},
                            }
                        }
                    }
                },
            }
        }
    },
}


def _dm() -> DataModel:
    return DataModel(
        api_name="Aha",
        entities=[
            Entity(name="Feature", collection="features", primary_key="id", fields=[])
        ],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


def test_extract_operations_pulls_stub_fields() -> None:
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


def test_extract_operations_uses_sanitized_ids() -> None:
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


async def test_analyze_orchestrates_extract_classify_merge() -> None:
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


def test_inline_schema_evidence_collects_request_and_response() -> None:
    ev = A.inline_schema_evidence(OpenAPISpec(RPC_SPEC))
    assert ev["get_user__request"] == {
        "type": "object",
        "properties": {"user_id": {"type": "string"}},
    }
    # response unwraps the tool-style {"returns": {...}} envelope
    assert set(ev["get_user__response"]["properties"]) == {"user_id", "name"}


def test_inline_schema_evidence_skips_ops_without_bodies() -> None:
    # SPEC has no requestBody and a schema-less 200 response.
    assert A.inline_schema_evidence(OpenAPISpec(SPEC)) == {}


async def test_analyze_falls_back_to_inline_when_no_components() -> None:
    captured: dict = {}

    async def fake_extract(source: Any, slug: Any, llm: Any, *, retries: Any) -> Any:
        captured["source"] = source
        return _dm()

    records = [{"operation_id": "get_user", "kind": "read", "patterns": []}]
    with (
        patch.object(A, "extract_data_model", AsyncMock(side_effect=fake_extract)),
        patch.object(A, "classify_batch", AsyncMock(return_value=records)),
    ):
        ir = await A.analyze(
            RPC_SPEC,
            "booker",
            extract_llm=object(),
            classify_llm=object(),
            retries=0,
            batch_cap=40,
            concurrency=5,
        )
    assert "get_user__request" in captured["source"]
    assert "get_user__response" in captured["source"]
    assert ir.operations[0].operation_id == "get_user"


async def test_analyze_prefers_components_over_inline() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Aha", "version": "1.0"},
        "components": {"schemas": {"Feature": {"type": "object"}}},
        "paths": {
            "/get_user": {
                "post": {
                    "operationId": "get_user",
                    "requestBody": {
                        "content": {"application/json": {"schema": {"type": "object"}}}
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    captured: dict = {}

    async def fake_extract(source: Any, slug: Any, llm: Any, *, retries: Any) -> Any:
        captured["source"] = source
        return _dm()

    records = [{"operation_id": "get_user", "kind": "read", "patterns": []}]
    with (
        patch.object(A, "extract_data_model", AsyncMock(side_effect=fake_extract)),
        patch.object(A, "classify_batch", AsyncMock(return_value=records)),
    ):
        await A.analyze(
            spec,
            "aha",
            extract_llm=object(),
            classify_llm=object(),
            retries=0,
            batch_cap=40,
            concurrency=5,
        )
    # components.schemas wins; inline bodies are ignored.
    assert captured["source"] == {"Feature": {"type": "object"}}


async def test_analyze_raises_when_no_entities_extracted() -> None:
    empty_dm = DataModel(
        api_name="x",
        entities=[],
        store_metadata=StoreMetadata(collections=[], pk_map={}),
    )
    with patch.object(A, "extract_data_model", AsyncMock(return_value=empty_dm)):
        with pytest.raises(GenerationStageError) as exc:
            await A.analyze(
                RPC_SPEC,
                "x",
                extract_llm=object(),
                classify_llm=object(),
                retries=0,
                batch_cap=40,
                concurrency=5,
            )
    assert exc.value.stage == "extract"


async def test_analyze_raises_on_coverage_gap() -> None:
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
