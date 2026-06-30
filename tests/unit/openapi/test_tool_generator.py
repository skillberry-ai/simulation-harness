"""Unit tests for tool generator."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from simulation_harness.openapi.parser import load_openapi_spec
from simulation_harness.openapi.tool_generator import (
    ToolGenerationError,
    generate_tool_from_operation,
    generate_tools_from_spec,
    get_optional_parameters,
    get_required_parameters,
    get_tool_by_name,
)
from collections.abc import Iterator


@pytest.fixture
def temp_dir() -> Iterator[Any]:
    """Create temporary directory for test files."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def simple_openapi_spec() -> dict[str, Any]:
    """Simple OpenAPI specification with one operation."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "summary": "List all users",
                    "description": "Returns a list of all users",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                            "description": "Maximum number of users to return",
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


@pytest.fixture
def complex_openapi_spec() -> dict[str, Any]:
    """Complex OpenAPI specification with multiple operations."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "summary": "Create a user",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["name", "email"],
                                    "properties": {
                                        "name": {"type": "string"},
                                        "email": {"type": "string", "format": "email"},
                                        "age": {"type": "integer"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            },
            "/users/{id}": {
                "get": {
                    "operationId": "getUser",
                    "summary": "Get a user",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "Success"}},
                }
            },
        },
    }


def test_generate_tools_from_simple_spec(
    temp_dir: Path, simple_openapi_spec: dict[str, Any]
) -> None:
    """Test generating tools from simple specification."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(simple_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    tools = generate_tools_from_spec(spec)

    assert len(tools) == 1
    assert tools[0]["name"] == "listUsers"
    assert "List all users" in tools[0]["description"]


def test_generate_tools_from_complex_spec(
    temp_dir: Path, complex_openapi_spec: dict[str, Any]
) -> None:
    """Test generating tools from complex specification."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(complex_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    tools = generate_tools_from_spec(spec)

    assert len(tools) == 2
    tool_names = [t["name"] for t in tools]
    assert "createUser" in tool_names
    assert "getUser" in tool_names


def test_tool_input_schema_with_parameters(
    temp_dir: Path, simple_openapi_spec: dict[str, Any]
) -> None:
    """Test tool input schema includes parameters."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(simple_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    tools = generate_tools_from_spec(spec)

    tool = tools[0]
    assert "limit" in tool["inputSchema"]["properties"]
    assert tool["inputSchema"]["properties"]["limit"]["type"] == "integer"


def test_tool_input_schema_with_request_body(
    temp_dir: Path, complex_openapi_spec: dict[str, Any]
) -> None:
    """Test tool input schema includes request body properties."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(complex_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    tools = generate_tools_from_spec(spec)

    create_tool = get_tool_by_name(tools, "createUser")
    assert create_tool is not None

    # Check properties from request body
    assert "name" in create_tool["inputSchema"]["properties"]
    assert "email" in create_tool["inputSchema"]["properties"]
    assert "age" in create_tool["inputSchema"]["properties"]

    # Check required fields
    assert "name" in create_tool["inputSchema"]["required"]
    assert "email" in create_tool["inputSchema"]["required"]
    assert "age" not in create_tool["inputSchema"]["required"]


def test_tool_required_parameters(
    temp_dir: Path, complex_openapi_spec: dict[str, Any]
) -> None:
    """Test getting required parameters from tool."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(complex_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    tools = generate_tools_from_spec(spec)

    get_tool = get_tool_by_name(tools, "getUser")
    assert get_tool is not None

    required = get_required_parameters(get_tool)
    assert "id" in required


def test_tool_optional_parameters(
    temp_dir: Path, simple_openapi_spec: dict[str, Any]
) -> None:
    """Test getting optional parameters from tool."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(simple_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    tools = generate_tools_from_spec(spec)

    tool = tools[0]
    optional = get_optional_parameters(tool)
    assert "limit" in optional


def test_get_tool_by_name(temp_dir: Path, complex_openapi_spec: dict[str, Any]) -> None:
    """Test getting tool by name."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(complex_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    tools = generate_tools_from_spec(spec)

    tool = get_tool_by_name(tools, "createUser")
    assert tool is not None
    assert tool["name"] == "createUser"

    # Non-existent tool
    assert get_tool_by_name(tools, "nonexistent") is None


def test_tool_description_includes_http_info(
    temp_dir: Path, simple_openapi_spec: dict[str, Any]
) -> None:
    """Test that tool description includes HTTP method and path."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(simple_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    tools = generate_tools_from_spec(spec)

    tool = tools[0]
    assert "GET /users" in tool["description"]


def test_generate_tool_from_operation(
    temp_dir: Path, simple_openapi_spec: dict[str, Any]
) -> None:
    """Test generating single tool from operation."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(simple_openapi_spec, f)

    spec = load_openapi_spec(spec_file, validate_spec=False)
    operation = spec.operations[0]

    tool = generate_tool_from_operation(operation, spec)

    assert tool["name"] == "listUsers"
    assert tool["description"]
    assert tool["inputSchema"]


def test_tool_generation_error() -> None:
    """Test that ToolGenerationError can be raised."""
    # This is a simple test to ensure the exception exists
    with pytest.raises(ToolGenerationError):
        raise ToolGenerationError("Test error")


# Made with Bob
