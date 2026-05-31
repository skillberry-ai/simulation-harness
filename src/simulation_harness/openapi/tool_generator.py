"""Tool generator from OpenAPI specifications.

This module converts OpenAPI operations into tool definitions.
"""

from typing import Any

from .parser import OpenAPIOperation, OpenAPISpec


class ToolGenerationError(Exception):
    """Raised when tool generation fails."""

    pass


def generate_tools_from_spec(spec: OpenAPISpec) -> list[dict[str, Any]]:
    """Generate tools from OpenAPI specification.

    Args:
        spec: Parsed OpenAPI specification

    Returns:
        List of tool dictionaries

    Raises:
        ToolGenerationError: If tool generation fails
    """
    tools = []

    for operation in spec.operations:
        try:
            tool = generate_tool_from_operation(operation, spec)
            tools.append(tool)
        except Exception as e:
            raise ToolGenerationError(
                f"Failed to generate tool for operation {operation.operation_id}: {e}"
            ) from e

    return tools


def generate_tool_from_operation(operation: OpenAPIOperation, spec: OpenAPISpec) -> dict[str, Any]:
    """Generate tool from OpenAPI operation.

    Args:
        operation: OpenAPI operation
        spec: Full OpenAPI specification (for resolving references)

    Returns:
        Tool dictionary with name, description, and inputSchema
    """
    # Build tool description
    description = _build_tool_description(operation)

    # Build input schema
    input_schema = _build_input_schema(operation, spec)

    # Create tool dictionary
    tool = {
        "name": operation.operation_id,
        "description": description,
        "inputSchema": input_schema,
    }

    return tool


def _build_tool_description(operation: OpenAPIOperation) -> str:
    """Build tool description from operation metadata.

    Args:
        operation: OpenAPI operation

    Returns:
        Tool description string
    """
    parts = []

    # Add summary
    if operation.summary:
        parts.append(operation.summary)

    # Add description if different from summary
    if operation.description and operation.description != operation.summary:
        parts.append(operation.description)

    # Add HTTP method and path
    parts.append(f"HTTP: {operation.method.upper()} {operation.path}")

    return "\n\n".join(parts)


def _build_input_schema(operation: OpenAPIOperation, spec: OpenAPISpec) -> dict[str, Any]:
    """Build JSON schema for tool input from operation parameters and request body.

    Args:
        operation: OpenAPI operation
        spec: Full OpenAPI specification

    Returns:
        JSON schema for tool input
    """
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": True,
    }

    # Add parameters to schema
    for param in operation.parameters:
        param_name = param["name"]
        param_schema = param.get("schema", {"type": "string"})
        param_description = param.get("description", "")

        # Add parameter to properties
        schema["properties"][param_name] = {
            **param_schema,
            "description": param_description,
        }

        # Add to required if parameter is required
        if param.get("required", False):
            schema["required"].append(param_name)

    # Add request body to schema if present
    request_schema = operation.get_request_schema()
    if request_schema:
        # Resolve $ref if present
        if "$ref" in request_schema:
            request_schema = spec.resolve_ref(request_schema["$ref"]) or request_schema

        # If request body is an object, merge its properties
        if request_schema.get("type") == "object":
            properties = request_schema.get("properties", {})
            for prop_name, prop_schema in properties.items():
                # Resolve nested $refs
                if isinstance(prop_schema, dict) and "$ref" in prop_schema:
                    prop_schema = spec.resolve_ref(prop_schema["$ref"]) or prop_schema

                schema["properties"][prop_name] = prop_schema

            # Add required fields from request body
            required_fields = request_schema.get("required", [])
            for field in required_fields:
                if field not in schema["required"]:
                    schema["required"].append(field)
        else:
            # If request body is not an object, add it as a single "body" parameter
            schema["properties"]["body"] = request_schema
            schema["required"].append("body")

    # Remove required array if empty
    if not schema["required"]:
        del schema["required"]

    return schema


def get_tool_by_name(tools: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Get tool by name from list of tools.

    Args:
        tools: List of tool dictionaries
        name: Tool name (operation ID)

    Returns:
        Tool if found, None otherwise
    """
    for tool in tools:
        if tool["name"] == name:
            return tool
    return None


def get_required_parameters(tool: dict[str, Any]) -> list[str]:
    """Get list of required parameter names for a tool.

    Args:
        tool: Tool dictionary

    Returns:
        List of required parameter names
    """
    schema = tool["inputSchema"]
    result = schema.get("required", [])
    return result if isinstance(result, list) else []


def get_optional_parameters(tool: dict[str, Any]) -> list[str]:
    """Get list of optional parameter names for a tool.

    Args:
        tool: Tool dictionary

    Returns:
        List of optional parameter names
    """
    schema = tool["inputSchema"]
    all_params = list(schema.get("properties", {}).keys())
    required = schema.get("required", [])
    return [p for p in all_params if p not in required]

# Made with Bob
