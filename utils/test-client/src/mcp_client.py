"""MCP client for simulation harness."""

import time
from typing import Any, Optional

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from pydantic import BaseModel


class MCPResponse(BaseModel):
    """Standardized MCP response."""

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float


class HarnessMCPClient:
    """Client for harness MCP interface."""

    def __init__(self, base_url: str):
        """Initialize MCP client.

        Args:
            base_url: Base URL of harness (e.g., http://localhost:8086)
        """
        self.base_url = base_url.rstrip("/")

    async def list_tools(self) -> MCPResponse:
        """List available MCP tools via MCP SSE protocol.

        Returns:
            MCPResponse with list of tools
        """
        start = time.time()
        try:
            async with sse_client(f"{self.base_url}/mcp/sse") as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()

            duration_ms = (time.time() - start) * 1000
            
            # Convert tools to dict format
            tools_data = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
                for tool in result.tools
            ]
            
            # Debug logging
            print(f"[MCP Client] list_tools() returned {len(tools_data)} tools")
            print(f"[MCP Client] Tools: {tools_data}")
            
            return MCPResponse(
                success=True,
                data=tools_data,
                error=None,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            print(f"[MCP Client] list_tools() error: {e}")
            import traceback
            traceback.print_exc()
            return MCPResponse(
                success=False,
                data=None,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPResponse:
        """Call an MCP tool.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            MCPResponse with tool result
        """
        start = time.time()
        try:
            async with sse_client(f"{self.base_url}/mcp/sse") as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)

            duration_ms = (time.time() - start) * 1000
            text_content = "\n".join(
                item.text for item in result.content if getattr(item, "type", None) == "text"
            )

            return MCPResponse(
                success=not result.isError,
                data={"content": text_content, "isError": result.isError},
                error=text_content if result.isError else None,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return MCPResponse(
                success=False,
                data=None,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def close(self) -> None:
        """Close the MCP client."""
        return None


# Made with Bob
