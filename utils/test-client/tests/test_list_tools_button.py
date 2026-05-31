"""Test for List Tools button functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from lib.mcp_client import MCPResponse


@pytest.mark.asyncio
async def test_list_tools_returns_data():
    """Test that list_tools returns properly formatted data."""
    from lib.mcp_client import HarnessMCPClient
    
    # Mock the SSE client and session
    mock_tool = MagicMock()
    mock_tool.name = "test_tool"
    mock_tool.description = "A test tool"
    mock_tool.inputSchema = {"type": "object"}
    
    mock_result = MagicMock()
    mock_result.tools = [mock_tool]
    
    with patch("lib.mcp_client.sse_client") as mock_sse:
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        
        mock_streams = (MagicMock(), MagicMock())
        mock_sse.return_value.__aenter__ = AsyncMock(return_value=mock_streams)
        mock_sse.return_value.__aexit__ = AsyncMock(return_value=None)
        
        with patch("lib.mcp_client.ClientSession", return_value=mock_session):
            client = HarnessMCPClient("http://localhost:8086")
            response = await client.list_tools()
    
    # Verify response structure
    assert response.success is True
    assert response.error is None
    assert response.data is not None
    assert len(response.data) == 1
    assert response.data[0]["name"] == "test_tool"
    assert response.data[0]["description"] == "A test tool"
    assert response.data[0]["inputSchema"] == {"type": "object"}


def test_list_tools_button_pattern():
    """Test that demonstrates the button pattern issue.
    
    This test shows that UI updates inside asyncio.run() don't
    trigger Streamlit re-renders.
    """
    # This is a documentation test showing the problem pattern
    # The actual fix will move UI rendering outside asyncio.run()
    
    # BROKEN PATTERN (current code):
    # if st.button("List Tools"):
    #     async def list_tools():
    #         response = await client.list_tools()
    #         st.success(...)  # <- This doesn't trigger re-render!
    #     asyncio.run(list_tools())
    
    # FIXED PATTERN (what we need):
    # if st.button("List Tools"):
    #     async def list_tools():
    #         response = await client.list_tools()
    #         return response  # <- Return data instead
    #     response = asyncio.run(list_tools())
    #     st.success(...)  # <- UI updates in main context
    
    assert True  # Documentation test

# Made with Bob
