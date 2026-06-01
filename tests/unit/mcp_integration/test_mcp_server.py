"""Tests for MCP server wrapper."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from simulation_harness.mcp_integration.mcp_server import MCPServerWrapper
from simulation_harness.core.simulation_instance import SimulationInstance
from simulation_harness.models.domain import SimulationSpec, ToolCallResult
from simulation_harness.utils.errors import SessionExpiredError, ConcurrentQueueFullError


@pytest.fixture
def mock_simulation_instance():
    """Create a mock simulation instance."""
    instance = Mock(spec=SimulationInstance)
    instance.execute_tool = AsyncMock()
    instance.spec = Mock(spec=SimulationSpec)
    instance.spec.openapi_spec = {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/test": {
                "get": {
                    "operationId": "getTest",
                    "summary": "Get test data",
                    "responses": {"200": {"description": "Success"}},
                }
            }
        },
    }
    return instance


@pytest.mark.asyncio
async def test_mcp_server_wrapper_initialization(mock_simulation_instance):
    """Test that MCPServerWrapper initializes correctly."""
    wrapper = MCPServerWrapper(mock_simulation_instance)
    
    assert wrapper.simulation_instance == mock_simulation_instance
    assert wrapper.server is not None


@pytest.mark.asyncio
async def test_list_tools_returns_tool_schemas(mock_simulation_instance):
    """Test that list_tools returns correct tool schemas from OpenAPI operations."""
    wrapper = MCPServerWrapper(mock_simulation_instance)
    
    # Call list_tools handler
    tools = await wrapper.list_tools()
    
    # Should return list of tool schemas
    assert isinstance(tools, list)
    assert len(tools) > 0
    
    # Check first tool has required MCP tool schema fields
    tool = tools[0]
    assert "name" in tool
    assert "description" in tool
    assert "inputSchema" in tool
    assert tool["name"] == "getTest"


@pytest.mark.asyncio
async def test_call_tool_executes_via_simulation_instance(mock_simulation_instance):
    """Test that call_tool executes via SimulationInstance.execute_tool."""
    mock_simulation_instance.execute_tool.return_value = ToolCallResult(
        success=True,
        content='{"result": "success"}',
        error=None,
    )
    
    wrapper = MCPServerWrapper(mock_simulation_instance)
    
    # Call tool
    result = await wrapper.call_tool("getTest", {})
    
    # Should call simulation instance
    mock_simulation_instance.execute_tool.assert_called_once_with("getTest", {})
    
    # Should return MCP result format
    assert isinstance(result, dict)
    assert "content" in result
    assert result["isError"] is False


@pytest.mark.asyncio
async def test_call_tool_handles_session_expired_error(mock_simulation_instance):
    """Test that SessionExpiredError is translated to MCP error result."""
    mock_simulation_instance.execute_tool.side_effect = SessionExpiredError(
        reason="max_messages_exceeded",
        limit=100,
        observed=101
    )
    
    wrapper = MCPServerWrapper(mock_simulation_instance)
    
    # Call tool
    result = await wrapper.call_tool("getTest", {})
    
    # Should return MCP error result
    assert isinstance(result, dict)
    assert result["isError"] is True
    assert "Session expired" in str(result["content"])


@pytest.mark.asyncio
async def test_call_tool_handles_queue_full_error(mock_simulation_instance):
    """Test that ConcurrentQueueFullError is translated to MCP error result."""
    mock_simulation_instance.execute_tool.side_effect = ConcurrentQueueFullError(
        "Queue is full (depth=10, max=10)"
    )
    
    wrapper = MCPServerWrapper(mock_simulation_instance)
    
    # Call tool
    result = await wrapper.call_tool("getTest", {})
    
    # Should return MCP error result
    assert isinstance(result, dict)
    assert result["isError"] is True
    assert "Queue is full" in str(result["content"])


@pytest.mark.asyncio
async def test_call_tool_handles_tool_execution_failure(mock_simulation_instance):
    """Test that tool execution failures are properly returned."""
    mock_simulation_instance.execute_tool.return_value = ToolCallResult(
        success=False,
        content="",
        error="Tool execution failed",
    )
    
    wrapper = MCPServerWrapper(mock_simulation_instance)
    
    # Call tool
    result = await wrapper.call_tool("getTest", {})
    
    # Should return MCP error result
    assert isinstance(result, dict)
    assert result["isError"] is True
    assert "Tool execution failed" in str(result["content"])


@pytest.mark.asyncio
async def test_call_tool_with_arguments(mock_simulation_instance):
    """Test that call_tool passes arguments correctly."""
    mock_simulation_instance.execute_tool.return_value = ToolCallResult(
        success=True,
        content='{"id": 123}',
        error=None,
    )
    
    wrapper = MCPServerWrapper(mock_simulation_instance)
    
    # Call tool with arguments
    args = {"id": 123, "name": "test"}
    result = await wrapper.call_tool("getTest", args)
    
    # Should pass arguments to simulation instance
    mock_simulation_instance.execute_tool.assert_called_once_with("getTest", args)
    
    # Should return success result
    assert result["isError"] is False


# Made with Bob