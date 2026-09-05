"""Tests for schema-source selection feeding the identity rule."""

from __future__ import annotations

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.stages.analyze.sources import (
    collect_sources,
    dedup_by_value,
)


def test_dedup_by_value_drops_identical_shapes() -> None:
    shape = {"type": "object", "properties": {"order_id": {"type": "string"}}}
    out = dedup_by_value({"b__response": dict(shape), "a__response": dict(shape)})
    # Sorted iteration means the alphabetically-first name survives, so the
    # survivor does not depend on how the input map was built.
    assert list(out) == ["a__response"]


def test_dedup_by_value_keeps_distinct_shapes() -> None:
    out = dedup_by_value(
        {
            "a": {"properties": {"x": {"type": "string"}}},
            "b": {"properties": {"y": {"type": "string"}}},
        }
    )
    assert list(out) == ["a", "b"]


def test_collect_sources_named_spec_uses_components() -> None:
    spec_dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": {},
        "components": {"schemas": {"Order": {"properties": {"id": {}}}}},
    }
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
    assert sources.synthetic is False
    assert list(sources.identity) == ["Order"]
    assert list(sources.enrich) == ["Order"]


def test_collect_sources_synthetic_identity_is_responses_only() -> None:
    paths = {
        "/create": {
            "post": {
                "operationId": "create_order",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"note": {"type": "string"}},
                            }
                        }
                    }
                },
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"order_id": {"type": "string"}},
                                }
                            }
                        }
                    }
                },
            }
        }
    }
    spec_dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": paths,
    }
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
    assert sources.synthetic is True
    # A request body is a projection of an entity, not the entity — it must not
    # reach the identity rule.
    assert list(sources.identity) == ["create_order"]
    assert sorted(sources.enrich) == ["create_order__request", "create_order__response"]


def test_collect_sources_synthetic_unwraps_returns_envelope() -> None:
    inner = {"type": "object", "properties": {"user_id": {"type": "string"}}}
    paths = {
        "/get": {
            "post": {
                "operationId": "get_user",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"returns": inner},
                                }
                            }
                        }
                    }
                },
            }
        }
    }
    spec_dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": paths,
    }
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
    assert sources.identity["get_user"] == inner


def test_collect_sources_synthetic_skips_non_object_responses() -> None:
    paths = {
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
    }
    spec_dict = {
        "openapi": "3.0.0",
        "info": {"title": "T", "version": "1"},
        "paths": paths,
    }
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
    assert sources.identity == {}
