"""Tests for SidecarMCPServer."""

import asyncio
import json
import socket
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from simulation_harness.config.models import MCPConfig, TransportType
from simulation_harness.mcp_integration.sidecar_server import (
    SidecarMCPServer,
    _check_port_available,
)
from simulation_harness.utils.errors import PortInUseError


def _spec() -> dict[str, Any]:
    return {
        "openapi": "3.0.0",
        "info": {"title": "Sidecar Test API", "version": "1.0.0"},
        "paths": {
            "/ping": {
                "get": {
                    "operationId": "ping",
                    "summary": "Ping",
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }


def _parse_sse_json(body: str) -> dict[str, Any]:
    for line in body.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"no SSE data line in response body: {body!r}")


class TestCheckPortAvailable:
    """Tests for _check_port_available helper."""

    def test_raises_port_in_use_error_when_port_taken(self) -> None:
        """When a port is already bound, raises PortInUseError."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", 0))
            taken_port = sock.getsockname()[1]
            with pytest.raises(PortInUseError) as exc_info:
                _check_port_available(taken_port)
            assert str(taken_port) in str(exc_info.value)
        finally:
            sock.close()

    def test_does_not_raise_when_port_is_free(self) -> None:
        """When port is available, does not raise."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("0.0.0.0", 0))
        free_port = sock.getsockname()[1]
        sock.close()
        # Should not raise
        _check_port_available(free_port)


class TestSidecarMCPServer:
    """Tests for SidecarMCPServer."""

    @pytest.fixture
    def mock_instance(self) -> MagicMock:
        from simulation_harness.core.simulation_instance import SimulationInstance

        return MagicMock(spec=SimulationInstance)

    @pytest.fixture
    def sse_config(self) -> MCPConfig:
        return MCPConfig(transport=TransportType.SSE)

    @pytest.mark.asyncio
    async def test_start_raises_port_in_use_error(
        self, mock_instance: MagicMock, sse_config: MCPConfig
    ) -> None:
        """start() raises PortInUseError when port pre-check fails."""
        sidecar = SidecarMCPServer(mock_instance, 9000, sse_config)
        with patch(
            "simulation_harness.mcp_integration.sidecar_server._check_port_available",
            side_effect=PortInUseError("Port 9000 is already in use"),
        ):
            with pytest.raises(PortInUseError):
                await sidecar.start()

    @pytest.mark.asyncio
    async def test_start_creates_uvicorn_task(
        self, mock_instance: MagicMock, sse_config: MCPConfig
    ) -> None:
        """start() creates an asyncio task running the uvicorn server."""
        sidecar = SidecarMCPServer(mock_instance, 9001, sse_config)

        mock_server = MagicMock()
        mock_server.started = True
        serve_called = []

        async def fake_serve() -> None:
            serve_called.append(True)

        mock_server.serve = fake_serve

        with (
            patch(
                "simulation_harness.mcp_integration.sidecar_server._check_port_available"
            ),
            patch(
                "simulation_harness.mcp_integration.sidecar_server.uvicorn.Server",
                return_value=mock_server,
            ),
        ):
            await sidecar.start()

        assert sidecar._server_task is not None
        await asyncio.sleep(0)
        assert serve_called

    @pytest.mark.asyncio
    async def test_stop_signals_server_exit(
        self, mock_instance: MagicMock, sse_config: MCPConfig
    ) -> None:
        """stop() sets should_exit on the uvicorn server."""
        sidecar = SidecarMCPServer(mock_instance, 9002, sse_config)
        mock_server = MagicMock()
        mock_server.started = True
        mock_server.should_exit = False

        async def fake_serve() -> None:
            while not mock_server.should_exit:
                await asyncio.sleep(0.01)

        mock_server.serve = fake_serve

        with (
            patch(
                "simulation_harness.mcp_integration.sidecar_server._check_port_available"
            ),
            patch(
                "simulation_harness.mcp_integration.sidecar_server.uvicorn.Server",
                return_value=mock_server,
            ),
        ):
            await sidecar.start()

        await sidecar.stop()
        assert mock_server.should_exit is True

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_not_started(
        self, mock_instance: MagicMock, sse_config: MCPConfig
    ) -> None:
        """stop() does nothing when the sidecar was never started."""
        sidecar = SidecarMCPServer(mock_instance, 9003, sse_config)
        # Should not raise
        await sidecar.stop()

    def test_streamable_http_app_handles_initialize(self) -> None:
        """The streamable_http sidecar app completes an MCP initialize (issue #18).

        The old code constructed ``StreamableHTTPServerTransport()`` by hand and
        every ``POST /mcp`` 500'd with a missing ``mcp_session_id`` TypeError.
        """
        instance = MagicMock()
        instance.spec.openapi_spec = _spec()
        sidecar = SidecarMCPServer(
            instance, 9004, MCPConfig(transport=TransportType.STREAMABLE_HTTP)
        )

        app = sidecar._create_app()

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
        with TestClient(app) as client:
            resp = client.post(
                "/mcp",
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )

        assert resp.status_code == 200, resp.text
        payload = _parse_sse_json(resp.text)
        assert payload["result"]["serverInfo"]["name"] == "simulation-harness"
