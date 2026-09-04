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


async def test_analyze_derives_entities_from_inline_bodies() -> None:
    records = [{"operation_id": "get_user", "kind": "read", "patterns": []}]
    with (
        patch.object(A, "extract_data_model", AsyncMock()) as fallback,
        patch.object(A, "classify_batch", AsyncMock(return_value=records)),
    ):
        ir = await A.analyze(
            RPC_SPEC,
            "aha",
            extract_llm=object(),
            classify_llm=object(),
            retries=0,
            batch_cap=40,
            concurrency=5,
        )
    # Inline response bodies are decided in code now; no LLM call is needed.
    fallback.assert_not_awaited()
    assert ir.store_metadata.collections == ["users"]
    assert ir.store_metadata.pk_map == {"users": "user_id"}
    assert ir.identity_provenance == {"User": "derived"}
    assert ir.validate_consistency() == []


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

    async def fake_extract(
        source: Any, slug: Any, llm: Any, *, retries: Any, derived: Any = None
    ) -> Any:
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


NO_SCHEMA_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Bare", "version": "1.0"},
    "paths": {
        "/ping": {
            "get": {
                "operationId": "ping",
                "responses": {
                    "200": {
                        "content": {"application/json": {"schema": {"type": "string"}}}
                    }
                },
            }
        }
    },
}


async def test_analyze_raises_when_no_entities_extracted() -> None:
    empty_dm = DataModel(
        api_name="Bare",
        entities=[],
        store_metadata=StoreMetadata(collections=[], pk_map={}),
    )
    with (
        patch.object(A, "extract_data_model", AsyncMock(return_value=empty_dm)),
        pytest.raises(GenerationStageError) as exc,
    ):
        await A.analyze(
            NO_SCHEMA_SPEC,
            "x",
            extract_llm=object(),
            classify_llm=object(),
            retries=0,
            batch_cap=40,
            concurrency=5,
        )
    assert exc.value.stage == "extract"


# Request body carries a shape; the success response does not (no content on
# the 200). identity=_identity_responses only looks at responses, so it comes
# out empty and nothing is derived — but enrich=dedup_by_value(inline_schema_
# evidence(...)) still carries the request-body key. This distinguishes
# `sources.enrich` from `sources.identity`: if the 0-derived branch in
# analyze() ever handed over `sources.identity` instead of `sources.enrich`,
# this request-body evidence would silently vanish from the fallback's input.
REQUEST_ONLY_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "ReqOnly", "version": "1.0"},
    "paths": {
        "/create_widget": {
            "post": {
                "operationId": "create_widget",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"widget_name": {"type": "string"}},
                            }
                        }
                    }
                },
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


async def test_analyze_hands_the_whole_enrich_map_when_nothing_is_derived() -> None:
    captured: dict[str, Any] = {}

    async def fake_extract(
        source: Any, slug: Any, llm: Any, *, retries: Any, derived: Any = None
    ) -> Any:
        captured["source"] = source
        captured["derived"] = derived
        return DataModel(
            api_name="ReqOnly",
            entities=[
                Entity(
                    name="Widget",
                    collection="widgets",
                    primary_key="widget_id",
                    fields=[],
                )
            ],
            store_metadata=StoreMetadata(
                collections=["widgets"], pk_map={"widgets": "widget_id"}
            ),
        )

    records = [{"operation_id": "create_widget", "kind": "create", "patterns": []}]
    with (
        patch.object(A, "extract_data_model", AsyncMock(side_effect=fake_extract)),
        patch.object(A, "classify_batch", AsyncMock(return_value=records)),
    ):
        await A.analyze(
            REQUEST_ONLY_SPEC,
            "req-only",
            extract_llm=object(),
            classify_llm=object(),
            retries=0,
            batch_cap=40,
            concurrency=5,
        )
    # Nothing was derivable from the (schema-less) response, so the fallback
    # must see the whole enrich map — request-body evidence included — not
    # the (empty) identity map.
    assert "create_widget__request" in captured["source"]
    assert captured["derived"] is None


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


DESC_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Retail", "version": "1.0"},
    "paths": {
        "/cancel_pending_order": {
            "post": {
                "operationId": "cancel_pending_order",
                "summary": "Cancel a pending order.",
                "description": (
                    "Cancel a pending order. The status becomes 'cancelled' and "
                    "the payment is refunded to the gift card immediately."
                ),
                "responses": {"200": {"description": "ok"}},
            }
        },
        "/get_order": {
            "post": {
                "operationId": "get_order",
                "summary": "Get an order.",
                "description": "Get an order.",
                "responses": {"200": {"description": "ok"}},
            }
        },
        "/list_orders": {
            "post": {
                "operationId": "list_orders",
                "summary": "List orders.",
                "responses": {"200": {"description": "ok"}},
            }
        },
    },
}


def test_extract_operation_evidence_surfaces_description() -> None:
    ev = A.extract_operation_evidence(OpenAPISpec(DESC_SPEC))
    assert "refunded to the gift card" in (ev["cancel_pending_order"].description or "")


def test_extract_operation_evidence_drops_description_equal_to_summary() -> None:
    """6 of 16 tau2-retail ops duplicate summary into description; drop those."""
    ev = A.extract_operation_evidence(OpenAPISpec(DESC_SPEC))
    assert "get_order" not in ev


def test_extract_operation_evidence_omits_operations_without_description() -> None:
    """Sparse map: no description means no key, not an empty OperationEvidence."""
    ev = A.extract_operation_evidence(OpenAPISpec(DESC_SPEC))
    assert "list_orders" not in ev
    assert set(ev) == {"cancel_pending_order"}


def test_extract_operation_evidence_strips_whitespace_only_description() -> None:
    spec = OpenAPISpec(
        {
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1.0"},
            "paths": {
                "/t": {
                    "post": {
                        "operationId": "t",
                        "summary": "T.",
                        "description": "   \n  ",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )
    assert A.extract_operation_evidence(spec) == {}


def test_extract_operation_evidence_dedup_ignores_padding() -> None:
    """A padded description whose *stripped* form equals the summary is still
    redundant — the dedup comparison must run after stripping, not on the raw
    value. Uses an inline spec (not DESC_SPEC) so
    ``test_extract_operation_evidence_omits_operations_without_description``'s
    ``set(ev) == {"cancel_pending_order"}`` assertion stays true.
    """
    spec = OpenAPISpec(
        {
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1.0"},
            "paths": {
                "/t": {
                    "post": {
                        "operationId": "t",
                        "summary": "Get an order.",
                        "description": "  Get an order.  ",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )
    assert A.extract_operation_evidence(spec) == {}


def test_extract_operation_evidence_strips_surviving_description() -> None:
    """A surviving (non-redundant) description is stored stripped, not raw —
    pins rule 1's strip independently of rule 2's dedup."""
    spec = OpenAPISpec(
        {
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1.0"},
            "paths": {
                "/t": {
                    "post": {
                        "operationId": "t",
                        "summary": "Get an order.",
                        "description": "  Refunds the payment too.  ",
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )
    ev = A.extract_operation_evidence(spec)
    assert ev["t"].description == "Refunds the payment too."


def test_extract_operation_evidence_drops_non_string_description() -> None:
    """Runs before any LLM call, so a malformed description must not raise."""
    spec = OpenAPISpec(
        {
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1.0"},
            "paths": {
                "/t": {
                    "post": {
                        "operationId": "t",
                        "summary": "T.",
                        "description": {"unexpected": "object"},
                        "responses": {"200": {"description": "ok"}},
                    }
                }
            },
        }
    )
    assert A.extract_operation_evidence(spec) == {}


def test_extract_operations_returns_exactly_the_five_stub_keys() -> None:
    """REGRESSION GUARD — do not relax.

    classify_batch does `json.dumps(stubs, indent=2)`, dumping these dicts
    wholesale into the classify prompt. classify is a shape-only consumer, so any
    new key here silently inflates every classify request with content it must
    not see. Operation-level prose belongs in extract_operation_evidence.
    """
    for stub in A.extract_operations(OpenAPISpec(DESC_SPEC)):
        assert set(stub) == {"operation_id", "method", "path", "tag", "summary"}


async def test_analyze_populates_ir_evidence() -> None:
    dm = DataModel(
        api_name="Retail",
        entities=[
            Entity(
                name="Order",
                collection="orders",
                primary_key="order_id",
                fields=[{"name": "order_id", "type": "string", "required": True}],
            )
        ],
        store_metadata=StoreMetadata(
            collections=["orders"], pk_map={"orders": "order_id"}
        ),
    )
    semantics = [
        {"operation_id": "cancel_pending_order", "kind": "update", "entity": "Order"},
        {"operation_id": "get_order", "kind": "read", "entity": "Order"},
        {"operation_id": "list_orders", "kind": "list", "entity": "Order"},
    ]
    with (
        patch.object(A, "extract_data_model", AsyncMock(return_value=dm)),
        patch.object(A, "classify_batch", AsyncMock(return_value=semantics)),
    ):
        ir = await A.analyze(
            DESC_SPEC,
            "retail",
            extract_llm=object(),
            classify_llm=object(),
            retries=0,
            batch_cap=40,
            concurrency=1,
        )

    assert "refunded to the gift card" in (
        ir.evidence["cancel_pending_order"].description or ""
    )
    assert set(ir.evidence) == {"cancel_pending_order"}
    assert ir.validate_consistency() == []


async def test_analyze_hands_only_undecidable_schemas_to_the_fallback() -> None:
    spec: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {"title": "Mixed", "version": "1.0"},
        "paths": {},
        "components": {
            "schemas": {
                "Order": {"properties": {"order_id": {"type": "string"}}},
                "Error": {"properties": {"message": {"type": "string"}}},
            }
        },
    }
    captured: dict[str, Any] = {}

    async def fake_extract(
        source: Any, slug: Any, llm: Any, *, retries: Any, derived: Any = None
    ) -> Any:
        captured["source"] = source
        captured["derived"] = derived
        return DataModel(
            api_name="Mixed",
            entities=[],
            store_metadata=StoreMetadata(collections=[], pk_map={}),
            declined=["Error"],
        )

    with (
        patch.object(A, "extract_data_model", AsyncMock(side_effect=fake_extract)),
        patch.object(A, "classify_batch", AsyncMock(return_value=[])),
    ):
        ir = await A.analyze(
            spec,
            "mixed",
            extract_llm=object(),
            classify_llm=object(),
            retries=0,
            batch_cap=40,
            concurrency=1,
        )
    assert list(captured["source"]) == ["Error"]
    assert captured["derived"].collections == ["orders"]
    assert ir.store_metadata.collections == ["orders"]
    assert ir.identity_provenance == {"Order": "derived"}
