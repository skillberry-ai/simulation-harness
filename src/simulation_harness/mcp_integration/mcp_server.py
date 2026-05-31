"""MCP server wrapper for simulation harness."""

from typing import Any

from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult

from simulation_harness.core.simulation_instance import SimulationInstance
from simulation_harness.openapi.parser import OpenAPISpec, OpenAPIOperation
from simulation_harness.utils.errors import SessionExpiredError, ConcurrentQueueFullError
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


class MCPServerWrapper:
    """Wrapper around mcp.server.Server that integrates with SimulationInstance."""

    def __init__(self, simulation_instance: SimulationInstance) -> None:
        """Initialize MCP server wrapper.

        Args:
            simulation_instance: The simulation instance to execute tools against
        """
        self.simulation_instance = simulation_instance
        self.server = Server("simulation-harness")
        
        # Cache parsed operations to avoid repeated parsing
        spec = OpenAPISpec(self.simulation_instance.spec.openapi_spec)
        self._operations = spec.operations
        
        # Register handlers
        self.server.list_tools()(self._handle_list_tools)
        self.server.call_tool()(self._handle_call_tool)
        
        logger.info(f"MCPServerWrapper initialized with {len(self._operations)} operations")

    async def _handle_list_tools(self) -> list[Tool]:
        """Handle list_tools request.

        Returns:
            List of MCP tool schemas derived from OpenAPI operations
        """
        # Use cached operations
        operations = self._operations
        
        tools = []
        for operation in operations:
            # Convert OpenAPI operation to MCP tool schema
            tool = Tool(
                name=operation.operation_id,
                description=operation.summary or operation.description or "",
                inputSchema={
                    "type": "object",
                    "properties": self._extract_properties(operation),
                    "required": self._extract_required(operation),
                },
            )
            tools.append(tool)
        
        logger.debug(f"Returning {len(tools)} tools")
        return tools

    def _extract_properties(self, operation) -> dict[str, Any]:
        """Extract properties from operation parameters and request body.

        Args:
            operation: OpenAPI operation

        Returns:
            Properties dictionary for JSON schema
        """
        properties = {}
        
        # Add parameters
        for param in operation.parameters:
            param_name = param.get("name", "")
            param_schema = param.get("schema", {})
            if param_name:
                properties[param_name] = param_schema
        
        # Add request body properties if present
        request_schema = operation.get_request_schema()
        if request_schema and "properties" in request_schema:
            properties.update(request_schema["properties"])
        
        return properties

    def _extract_required(self, operation) -> list[str]:
        """Extract required fields from operation.

        Args:
            operation: OpenAPI operation

        Returns:
            List of required field names
        """
        required = []
        
        # Add required parameters
        for param in operation.parameters:
            if param.get("required", False):
                param_name = param.get("name", "")
                if param_name:
                    required.append(param_name)
        
        # Add required request body fields
        request_schema = operation.get_request_schema()
        if request_schema and "required" in request_schema:
            required.extend(request_schema["required"])
        
        return required

    async def _handle_call_tool(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        """Handle call_tool request.

        Args:
            name: Tool name (operation ID)
            arguments: Tool arguments

        Returns:
            MCP CallToolResult with isError flag and content
        """
        try:
            # Execute tool via simulation instance
            result = await self.simulation_instance.execute_tool(name, arguments)
            
            if result.success:
                # Return success result
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=result.content,
                        )
                    ],
                    isError=False,
                )
            else:
                # Return error result from tool execution
                return CallToolResult(
                    content=[
                        TextContent(
                            type="text",
                            text=result.error or "Tool execution failed",
                        )
                    ],
                    isError=True,
                )
        
        except SessionExpiredError as e:
            # Translate session expired error to MCP error
            logger.warning(f"Session expired during tool call: {e}")
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Session expired: {str(e)}",
                    )
                ],
                isError=True,
            )
        
        except ConcurrentQueueFullError as e:
            # Translate queue full error to MCP error
            logger.warning(f"Queue full during tool call: {e}")
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"Queue full: {str(e)}",
                    )
                ],
                isError=True,
            )
        
        except Exception as e:
            # Log unexpected errors but don't expose internal details
            logger.error(f"Unexpected error during tool call: {e}", exc_info=True)
            # Re-raise to let MCP SDK handle it properly
            raise

    async def list_tools(self) -> list[dict[str, Any]]:
        """Public method to list tools (for testing).

        Returns:
            List of tool schemas as dictionaries
        """
        tools = await self._handle_list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
            for tool in tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Public method to call tool (for testing).

        Args:
            name: Tool name
            arguments: Tool arguments

        Returns:
            Result dictionary with isError flag and content
        """
        try:
            result = await self.simulation_instance.execute_tool(name, arguments)
            
            return {
                "isError": not result.success,
                "content": result.content if result.success else (result.error or "Tool execution failed"),
            }
        
        except (SessionExpiredError, ConcurrentQueueFullError) as e:
            return {
                "isError": True,
                "content": str(e),
            }
        
        except Exception as e:
            return {
                "isError": True,
                "content": f"Unexpected error: {str(e)}",
            }


# Made with Bob