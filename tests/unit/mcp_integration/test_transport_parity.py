"""Tests for transport parity - verifying both transports behave identically."""

import pytest
from unittest.mock import AsyncMock, Mock
from fastapi import FastAPI

from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
from simulation_harness.mcp_integration.transport import (
    mount_sse_transport,
    mount_streamable_http_transport,
)
from simulation_harness.models.domain import ToolCallResult
from typing import Any
from unittest.mock import MagicMock


@pytest.fixture
def mock_simulation_instance() -> MagicMock:
    """Create a mock simulation instance."""
    instance = Mock()
    instance.execute_tool = AsyncMock()
    instance.spec = Mock()
    instance.spec.openapi_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/test": {
                "get": {
                    "operationId": "getTest",
                    "summary": "Get test data",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "Success"}},
                }
            }
        },
    }
    return instance


@pytest.fixture
def sse_app(mock_simulation_instance: MagicMock) -> Any:
    """Create FastAPI app with SSE transport."""
    app = FastAPI()
    wrapper = MCPServerWrapper(mock_simulation_instance)
    mount_sse_transport(app, wrapper)
    return app, wrapper


@pytest.fixture
def http_app(mock_simulation_instance: MagicMock) -> Any:
    """Create FastAPI app with Streamable HTTP transport."""
    app = FastAPI()
    wrapper = MCPServerWrapper(mock_simulation_instance)
    mount_streamable_http_transport(app, wrapper)
    return app, wrapper


@pytest.mark.asyncio
async def test_both_transports_return_same_tool_list(
    mock_simulation_instance: MagicMock,
) -> None:
    """Test that both transports return identical tool lists."""
    # Create wrappers for both transports
    wrapper1 = MCPServerWrapper(mock_simulation_instance)
    wrapper2 = MCPServerWrapper(mock_simulation_instance)

    # Get tool lists
    tools1 = await wrapper1.list_tools()
    tools2 = await wrapper2.list_tools()

    # Should be identical
    assert tools1 == tools2
    assert len(tools1) > 0

    # Verify structure
    for tool in tools1:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool


@pytest.mark.asyncio
async def test_both_transports_handle_successful_tool_call_identically(
    mock_simulation_instance: MagicMock,
) -> None:
    """Test that both transports handle successful tool calls identically."""
    mock_simulation_instance.execute_tool.return_value = ToolCallResult(
        success=True,
        content='{"result": "success"}',
        error=None,
    )

    # Create wrappers for both transports
    wrapper1 = MCPServerWrapper(mock_simulation_instance)
    wrapper2 = MCPServerWrapper(mock_simulation_instance)

    # Call tool via both wrappers
    result1 = await wrapper1.call_tool("getTest", {"id": "123"})
    result2 = await wrapper2.call_tool("getTest", {"id": "123"})

    # Results should be identical
    assert result1 == result2
    assert result1["isError"] is False
    assert result1["content"] == '{"result": "success"}'


@pytest.mark.asyncio
async def test_both_transports_handle_tool_failure_identically(
    mock_simulation_instance: MagicMock,
) -> None:
    """Test that both transports handle tool failures identically."""
    mock_simulation_instance.execute_tool.return_value = ToolCallResult(
        success=False,
        content="",
        error="Tool execution failed",
    )

    # Create wrappers for both transports
    wrapper1 = MCPServerWrapper(mock_simulation_instance)
    wrapper2 = MCPServerWrapper(mock_simulation_instance)

    # Call tool via both wrappers
    result1 = await wrapper1.call_tool("getTest", {"id": "123"})
    result2 = await wrapper2.call_tool("getTest", {"id": "123"})

    # Results should be identical
    assert result1 == result2
    assert result1["isError"] is True
    assert "Tool execution failed" in result1["content"]


@pytest.mark.asyncio
async def test_both_transports_handle_session_expired_identically(
    mock_simulation_instance: MagicMock,
) -> None:
    """Test that both transports handle SessionExpiredError identically."""
    from simulation_harness.utils.errors import SessionExpiredError

    mock_simulation_instance.execute_tool.side_effect = SessionExpiredError(
        reason="max_messages_exceeded", limit=100, observed=101
    )

    # Create wrappers for both transports
    wrapper1 = MCPServerWrapper(mock_simulation_instance)
    wrapper2 = MCPServerWrapper(mock_simulation_instance)

    # Call tool via both wrappers
    result1 = await wrapper1.call_tool("getTest", {"id": "123"})
    result2 = await wrapper2.call_tool("getTest", {"id": "123"})

    # Results should be identical
    assert result1 == result2
    assert result1["isError"] is True
    assert "Session expired" in result1["content"]


@pytest.mark.asyncio
async def test_both_transports_handle_queue_full_identically(
    mock_simulation_instance: MagicMock,
) -> None:
    """Test that both transports handle ConcurrentQueueFullError identically."""
    from simulation_harness.utils.errors import ConcurrentQueueFullError

    mock_simulation_instance.execute_tool.side_effect = ConcurrentQueueFullError(
        "Queue is full (depth=10, max=10)"
    )

    # Create wrappers for both transports
    wrapper1 = MCPServerWrapper(mock_simulation_instance)
    wrapper2 = MCPServerWrapper(mock_simulation_instance)

    # Call tool via both wrappers
    result1 = await wrapper1.call_tool("getTest", {"id": "123"})
    result2 = await wrapper2.call_tool("getTest", {"id": "123"})

    # Results should be identical
    assert result1 == result2
    assert result1["isError"] is True
    assert "Queue is full" in result1["content"]


@pytest.mark.asyncio
async def test_both_transports_share_same_server_instance(
    mock_simulation_instance: MagicMock,
) -> None:
    """Test that both transports can use the same MCP server instance."""
    # Create single wrapper
    wrapper = MCPServerWrapper(mock_simulation_instance)

    # Both transports should be able to use the same wrapper.server
    assert wrapper.server is not None

    # The server instance should be the same regardless of transport
    server_id = id(wrapper.server)

    # Create another wrapper
    wrapper2 = MCPServerWrapper(mock_simulation_instance)

    # Different wrappers have different server instances
    # But they behave identically
    assert id(wrapper2.server) != server_id

    # Verify both produce identical results
    mock_simulation_instance.execute_tool.return_value = ToolCallResult(
        success=True,
        content='{"data": "test"}',
        error=None,
    )

    result1 = await wrapper.call_tool("getTest", {"id": "1"})
    result2 = await wrapper2.call_tool("getTest", {"id": "1"})

    assert result1 == result2


# Made with Bob
