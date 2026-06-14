"""Tests for SidecarMCPServer."""

import asyncio
import socket
from unittest.mock import MagicMock, patch

import pytest

from simulation_harness.config.models import MCPConfig, TransportType
from simulation_harness.mcp_integration.sidecar_server import (
    SidecarMCPServer,
    _check_port_available,
)
from simulation_harness.utils.errors import PortInUseError


class TestCheckPortAvailable:
    """Tests for _check_port_available helper."""

    def test_raises_port_in_use_error_when_port_taken(self):
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

    def test_does_not_raise_when_port_is_free(self):
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
    def mock_instance(self):
        from simulation_harness.core.simulation_instance import SimulationInstance

        return MagicMock(spec=SimulationInstance)

    @pytest.fixture
    def sse_config(self):
        return MCPConfig(transport=TransportType.SSE)

    @pytest.mark.asyncio
    async def test_start_raises_port_in_use_error(self, mock_instance, sse_config):
        """start() raises PortInUseError when port pre-check fails."""
        sidecar = SidecarMCPServer(mock_instance, 9000, sse_config)
        with patch(
            "simulation_harness.mcp_integration.sidecar_server._check_port_available",
            side_effect=PortInUseError("Port 9000 is already in use"),
        ):
            with pytest.raises(PortInUseError):
                await sidecar.start()

    @pytest.mark.asyncio
    async def test_start_creates_uvicorn_task(self, mock_instance, sse_config):
        """start() creates an asyncio task running the uvicorn server."""
        sidecar = SidecarMCPServer(mock_instance, 9001, sse_config)

        mock_server = MagicMock()
        mock_server.started = True
        serve_called = []

        async def fake_serve():
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
    async def test_stop_signals_server_exit(self, mock_instance, sse_config):
        """stop() sets should_exit on the uvicorn server."""
        sidecar = SidecarMCPServer(mock_instance, 9002, sse_config)
        mock_server = MagicMock()
        mock_server.started = True
        mock_server.should_exit = False

        async def fake_serve():
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
    async def test_stop_is_safe_when_not_started(self, mock_instance, sse_config):
        """stop() does nothing when the sidecar was never started."""
        sidecar = SidecarMCPServer(mock_instance, 9003, sse_config)
        # Should not raise
        await sidecar.stop()
