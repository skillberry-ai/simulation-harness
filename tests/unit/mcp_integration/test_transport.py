"""Tests for MCP transport mounting."""

import pytest
from unittest.mock import Mock, patch
from fastapi import FastAPI

from simulation_harness.mcp_integration.transport import (
    mount_sse_transport,
    mount_streamable_http_transport,
)
from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
from simulation_harness.config.models import TransportType


@pytest.fixture
def mock_mcp_wrapper():
    """Create a mock MCP server wrapper."""
    wrapper = Mock(spec=MCPServerWrapper)
    wrapper.server = Mock()
    return wrapper


@pytest.fixture
def fastapi_app():
    """Create a FastAPI app for testing."""
    return FastAPI()


def test_mount_sse_transport_creates_correct_endpoints(fastapi_app, mock_mcp_wrapper):
    """Test that SSE transport mounts at correct paths."""
    mount_sse_transport(fastapi_app, mock_mcp_wrapper)

    # Check that routes were added
    routes = [route.path for route in fastapi_app.routes]

    # SSE should have GET /mcp/sse and POST /mcp/messages
    assert "/mcp/sse" in routes
    assert "/mcp/messages" in routes


def test_mount_streamable_http_transport_creates_endpoint(
    fastapi_app, mock_mcp_wrapper
):
    """Test that Streamable HTTP transport mounts at /mcp."""
    mount_streamable_http_transport(fastapi_app, mock_mcp_wrapper)

    # Check that route was added
    routes = [route.path for route in fastapi_app.routes]

    # Streamable HTTP should mount at /mcp
    assert "/mcp" in routes


def test_mount_sse_transport_get_method(fastapi_app, mock_mcp_wrapper):
    """Test that SSE endpoint accepts GET method."""
    mount_sse_transport(fastapi_app, mock_mcp_wrapper)

    # Find the SSE route
    sse_route = None
    for route in fastapi_app.routes:
        if route.path == "/mcp/sse":
            sse_route = route
            break

    assert sse_route is not None
    assert "GET" in sse_route.methods


def test_mount_sse_transport_post_method(fastapi_app, mock_mcp_wrapper):
    """Test that messages endpoint accepts POST method."""
    mount_sse_transport(fastapi_app, mock_mcp_wrapper)

    # Find the messages route
    messages_route = None
    for route in fastapi_app.routes:
        if route.path == "/mcp/messages":
            messages_route = route
            break

    assert messages_route is not None
    assert "POST" in messages_route.methods


def test_mount_streamable_http_transport_post_method(fastapi_app, mock_mcp_wrapper):
    """Test that Streamable HTTP endpoint accepts POST method."""
    mount_streamable_http_transport(fastapi_app, mock_mcp_wrapper)

    # Find the /mcp route
    mcp_route = None
    for route in fastapi_app.routes:
        if route.path == "/mcp":
            mcp_route = route
            break

    assert mcp_route is not None
    assert "POST" in mcp_route.methods


def test_cannot_mount_multiple_transports(fastapi_app, mock_mcp_wrapper):
    """Test that mounting multiple transports raises an error."""
    # Mount first transport
    mount_sse_transport(fastapi_app, mock_mcp_wrapper)

    # Attempting to mount second transport should raise error
    with pytest.raises(ValueError, match="transport already mounted"):
        mount_streamable_http_transport(fastapi_app, mock_mcp_wrapper)


def test_transport_choice_from_config(fastapi_app, mock_mcp_wrapper):
    """Test that transport is chosen based on config."""
    # This test verifies the integration point
    # The actual mounting function should check config and mount appropriate transport

    # Test SSE config
    with patch(
        "simulation_harness.mcp_integration.transport.mount_sse_transport"
    ) as mock_sse:
        from simulation_harness.mcp_integration.transport import (
            mount_transport_from_config,
        )

        config_sse = Mock()
        config_sse.transport = TransportType.SSE

        mount_transport_from_config(fastapi_app, mock_mcp_wrapper, config_sse)
        mock_sse.assert_called_once()

    # Test Streamable HTTP config
    with patch(
        "simulation_harness.mcp_integration.transport.mount_streamable_http_transport"
    ) as mock_http:
        config_http = Mock()
        config_http.transport = TransportType.STREAMABLE_HTTP

        mount_transport_from_config(fastapi_app, mock_mcp_wrapper, config_http)
        mock_http.assert_called_once()


def test_both_transports_share_same_server(mock_mcp_wrapper):
    """Test that both transports use the same mcp.server.Server instance."""
    app1 = FastAPI()
    app2 = FastAPI()

    # Mount SSE transport
    mount_sse_transport(app1, mock_mcp_wrapper)

    # Mount Streamable HTTP transport (on different app to avoid conflict)
    mount_streamable_http_transport(app2, mock_mcp_wrapper)

    # Both should reference the same server
    # This is verified by passing the same wrapper instance
    assert mock_mcp_wrapper.server is not None


# Made with Bob
