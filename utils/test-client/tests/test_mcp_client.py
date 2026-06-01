"""Tests for MCP client."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.mcp_client import HarnessMCPClient


class _AsyncContextManager:
    """Simple async context manager wrapper for tests."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        return None


@pytest.mark.asyncio
async def test_list_tools_uses_rest_endpoint():
    """Test that list_tools uses REST endpoint instead of SSE."""
    mock_response = MagicMock()
    mock_response.json.return_value = [
        {
            "name": "getTest",
            "description": "Get test data",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("lib.mcp_client.httpx.AsyncClient", return_value=mock_client):
        client = HarnessMCPClient("http://localhost:8086")

        response = await client.list_tools()

    assert response.success is True
    assert response.error is None
    assert response.data == [
        {
            "name": "getTest",
            "description": "Get test data",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    mock_client.get.assert_awaited_once_with(
        "http://localhost:8086/api/v1/simulation/tools",
        timeout=5.0,
    )


@pytest.mark.asyncio
async def test_list_tools_returns_error_on_http_failure():
    """Test that list_tools returns a failed response when HTTP request fails."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=RuntimeError("Connection failed"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("lib.mcp_client.httpx.AsyncClient", return_value=mock_client):
        client = HarnessMCPClient("http://localhost:8086")

        response = await client.list_tools()

    assert response.success is False
    assert response.data is None
    assert response.error == "Connection failed"


@pytest.mark.asyncio
async def test_call_tool_uses_mcp_sse_session():
    """Test that call_tool uses MCP SSE transport and initializes session."""
    read_stream = object()
    write_stream = object()

    text_item = MagicMock()
    text_item.type = "text"
    text_item.text = '{"result":"ok"}'

    mock_result = MagicMock()
    mock_result.isError = False
    mock_result.content = [text_item]

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    with patch("lib.mcp_client.sse_client", return_value=_AsyncContextManager((read_stream, write_stream))) as mock_sse:
        with patch("lib.mcp_client.ClientSession", return_value=_AsyncContextManager(mock_session)) as mock_client_session:
            client = HarnessMCPClient("http://localhost:8086")

            response = await client.call_tool("getTest", {"id": "123"})

    assert response.success is True
    assert response.error is None
    assert response.data == {"content": '{"result":"ok"}', "isError": False}
    mock_sse.assert_called_once_with("http://localhost:8086/mcp/sse")
    mock_client_session.assert_called_once_with(read_stream, write_stream)
    mock_session.initialize.assert_awaited_once()
    mock_session.call_tool.assert_awaited_once_with("getTest", {"id": "123"})


@pytest.mark.asyncio
async def test_call_tool_returns_error_text_when_tool_fails():
    """Test that call_tool surfaces MCP tool errors."""
    read_stream = object()
    write_stream = object()

    text_item = MagicMock()
    text_item.type = "text"
    text_item.text = "Tool execution failed"

    mock_result = MagicMock()
    mock_result.isError = True
    mock_result.content = [text_item]

    mock_session = AsyncMock()
    mock_session.initialize = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    with patch("lib.mcp_client.sse_client", return_value=_AsyncContextManager((read_stream, write_stream))):
        with patch("lib.mcp_client.ClientSession", return_value=_AsyncContextManager(mock_session)):
            client = HarnessMCPClient("http://localhost:8086")

            response = await client.call_tool("getTest", {})

    assert response.success is False
    assert response.data == {"content": "Tool execution failed", "isError": True}
    assert response.error == "Tool execution failed"

# Made with Bob
