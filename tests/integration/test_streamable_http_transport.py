"""Integration tests for the MCP Streamable HTTP transport (POST /mcp).

Regression coverage for issue #18: with ``mcp.transport: streamable_http`` every
request to ``POST /mcp`` returned HTTP 500 because the transport was constructed
by hand without the SDK-required ``mcp_session_id`` argument. These tests drive
the endpoint over the real MCP JSON-RPC protocol and assert a 200 handshake and
that the OpenAPI operations surface as MCP tools.
"""

import importlib
import json
import os
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock


# Accept header the MCP Streamable HTTP transport requires for SSE responses.
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _spec() -> dict[str, Any]:
    """A minimal but valid OpenAPI spec with two operations."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Streamable Test API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "summary": "List all users",
                    "responses": {"200": {"description": "Success"}},
                },
                "post": {
                    "operationId": "createUser",
                    "summary": "Create a user",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                    "required": ["name"],
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "Created"}},
                },
            }
        },
    }


def _parse_sse_json(body: str) -> dict[str, Any]:
    """Extract the JSON-RPC payload from an SSE ``data:`` event body."""
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"no SSE data line in response body: {body!r}")


@pytest.fixture
def streamable_client() -> Iterator[TestClient]:
    """Reload the app under ``transport: streamable_http`` with a ready simulation.

    Mirrors ``tests/integration/test_database_endpoints.py::_make_app_with``:
    reloads ``simulation_harness.main`` so the module-level transport mounting
    picks up the streamable_http config, then overrides the simulation host with
    a ready record backed by a stub instance carrying the OpenAPI spec.
    """
    from simulation_harness.config.models import MCPConfig, TransportType
    import simulation_harness.config.settings as settings_module

    prior_path = os.environ.get("HARNESS_CONFIG_PATH")
    # The app lifespan calls load_secrets() on TestClient startup, which requires
    # LLM_API_KEY. CI has no .env, so provide a dummy key (mirrors
    # test_database_endpoints.py::_harness_env).
    prior_key = os.environ.get("LLM_API_KEY")
    os.environ["LLM_API_KEY"] = "test-key"

    # Patch the loaded config's transport rather than writing a full YAML file:
    # reload picks up whatever load_config returns, so wrap it to force streamable.
    real_load_config = settings_module.load_config

    def _load_streamable(path: str) -> Any:
        cfg = real_load_config(path)
        cfg.mcp = MCPConfig(transport=TransportType.STREAMABLE_HTTP)
        return cfg

    settings_module.load_config = _load_streamable  # type: ignore[assignment]
    try:
        import simulation_harness.main as m

        importlib.reload(m)
    finally:
        settings_module.load_config = real_load_config  # type: ignore[assignment]

    assert m.config.mcp.transport == TransportType.STREAMABLE_HTTP
    assert any(getattr(r, "path", None) == "/mcp" for r in m.app.routes), (
        "streamable_http transport did not mount POST /mcp"
    )

    from simulation_harness.api.dependencies import get_simulation_host
    from simulation_harness.core.simulation_host import SimulationHost
    from simulation_harness.core.simulation_record import (
        SimulationRecord,
        SimulationStatus,
    )

    instance = MagicMock()
    instance.spec.openapi_spec = _spec()

    host = SimulationHost()
    record = SimulationRecord.declare(name="streamable-test-api")
    record.transition(SimulationStatus.INITIALIZING, phase="agent_init")
    record.mark_ready(instance)
    host._record = record

    m.app.dependency_overrides[get_simulation_host] = lambda: host
    try:
        with TestClient(m.app) as client:
            yield client
    finally:
        m.app.dependency_overrides.clear()
        importlib.reload(m)
        if prior_path is not None:
            os.environ["HARNESS_CONFIG_PATH"] = prior_path
        elif "HARNESS_CONFIG_PATH" in os.environ:
            del os.environ["HARNESS_CONFIG_PATH"]
        if prior_key is not None:
            os.environ["LLM_API_KEY"] = prior_key
        else:
            os.environ.pop("LLM_API_KEY", None)


def test_initialize_handshake_returns_200(streamable_client: TestClient) -> None:
    """POST /mcp initialize completes the MCP handshake instead of 500ing."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
    }
    resp = streamable_client.post("/mcp", json=body, headers=_MCP_HEADERS)

    assert resp.status_code == 200, resp.text
    payload = _parse_sse_json(resp.text)
    assert payload["id"] == 1
    assert payload["result"]["serverInfo"]["name"] == "simulation-harness"
    assert "protocolVersion" in payload["result"]


def test_tools_list_returns_operations(streamable_client: TestClient) -> None:
    """POST /mcp tools/list surfaces the OpenAPI operations as MCP tools."""
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    headers = {**_MCP_HEADERS, "MCP-Protocol-Version": "2025-06-18"}

    resp = streamable_client.post("/mcp", json=body, headers=headers)

    assert resp.status_code == 200, resp.text
    payload = _parse_sse_json(resp.text)
    tool_names = {tool["name"] for tool in payload["result"]["tools"]}
    assert {"listUsers", "createUser"} <= tool_names
