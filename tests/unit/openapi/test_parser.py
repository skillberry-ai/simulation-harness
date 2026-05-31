"""Unit tests for OpenAPI parser."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from simulation_harness.openapi.parser import (
    OpenAPISpec,
    load_openapi_spec,
    validate_openapi_spec,
)
from simulation_harness.utils.errors import OpenAPIValidationError


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def minimal_openapi_30_spec() -> dict[str, Any]:
    """Minimal valid OpenAPI 3.0 specification."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {},
    }


@pytest.fixture
def minimal_openapi_31_spec() -> dict[str, Any]:
    """Minimal valid OpenAPI 3.1 specification."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {},
    }


@pytest.fixture
def full_openapi_spec() -> dict[str, Any]:
    """Full OpenAPI specification with operations."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0", "description": "A test API"},
        "servers": [{"url": "http://localhost:8000"}],
        "paths": {
            "/users": {
                "get": {
                    "operationId": "listUsers",
                    "summary": "List all users",
                    "description": "Returns a list of users",
                    "tags": ["users"],
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/User"},
                                    }
                                }
                            },
                        }
                    },
                },
                "post": {
                    "operationId": "createUser",
                    "summary": "Create a user",
                    "tags": ["users"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/User"}}
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "Created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            },
                        }
                    },
                },
            },
            "/users/{id}": {
                "get": {
                    "operationId": "getUser",
                    "summary": "Get a user",
                    "tags": ["users"],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/User"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "email": {"type": "string", "format": "email"},
                    },
                }
            }
        },
    }


def test_load_minimal_openapi_30_spec(temp_dir: Path, minimal_openapi_30_spec: dict[str, Any]):
    """Test loading minimal OpenAPI 3.0 specification."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(minimal_openapi_30_spec, f)

    spec = load_openapi_spec(spec_file)

    assert isinstance(spec, OpenAPISpec)
    assert spec.title == "Test API"
    assert spec.version == "1.0.0"
    assert len(spec.operations) == 0


def test_load_minimal_openapi_31_spec(temp_dir: Path, minimal_openapi_31_spec: dict[str, Any]):
    """Test loading minimal OpenAPI 3.1 specification."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(minimal_openapi_31_spec, f)

    spec = load_openapi_spec(spec_file)

    assert isinstance(spec, OpenAPISpec)
    assert spec.title == "Test API"
    assert spec.version == "1.0.0"
    assert len(spec.operations) == 0


def test_load_full_spec(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test loading full OpenAPI specification with operations."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    assert spec.title == "Test API"
    assert spec.description == "A test API"
    assert len(spec.operations) == 3
    assert len(spec.servers) == 1


def test_parse_operations(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test parsing operations from specification."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    # Check operations
    operation_ids = [op.operation_id for op in spec.operations]
    assert "listUsers" in operation_ids
    assert "createUser" in operation_ids
    assert "getUser" in operation_ids


def test_get_operation_by_id(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test getting operation by ID."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    operation = spec.get_operation_by_id("listUsers")
    assert operation is not None
    assert operation.method == "get"
    assert operation.path == "/users"
    assert operation.summary == "List all users"


def test_get_operations_by_tag(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test getting operations by tag."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    user_operations = spec.get_operations_by_tag("users")
    assert len(user_operations) == 3


def test_operation_request_schema(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test getting request schema from operation."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    # POST operation has request body
    create_op = spec.get_operation_by_id("createUser")
    assert create_op is not None
    request_schema = create_op.get_request_schema()
    assert request_schema is not None
    assert "$ref" in request_schema

    # GET operation has no request body
    list_op = spec.get_operation_by_id("listUsers")
    assert list_op is not None
    assert list_op.get_request_schema() is None


def test_operation_response_schema(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test getting response schema from operation."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    operation = spec.get_operation_by_id("listUsers")
    assert operation is not None

    response_schema = operation.get_response_schema("200")
    assert response_schema is not None
    assert response_schema["type"] == "array"


def test_operation_parameters(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test getting operation parameters."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    # List operation has optional parameter
    list_op = spec.get_operation_by_id("listUsers")
    assert list_op is not None
    assert len(list_op.parameters) == 1
    assert len(list_op.get_required_parameters()) == 0
    assert len(list_op.get_optional_parameters()) == 1

    # Get operation has required parameter
    get_op = spec.get_operation_by_id("getUser")
    assert get_op is not None
    assert len(get_op.parameters) == 1
    assert len(get_op.get_required_parameters()) == 1
    assert len(get_op.get_optional_parameters()) == 0


def test_get_schema(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test getting schema definition."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    user_schema = spec.get_schema("User")
    assert user_schema is not None
    assert user_schema["type"] == "object"
    assert "id" in user_schema["properties"]
    assert "name" in user_schema["properties"]


def test_resolve_ref(temp_dir: Path, full_openapi_spec: dict[str, Any]):
    """Test resolving $ref references."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    resolved = spec.resolve_ref("#/components/schemas/User")
    assert resolved is not None
    assert resolved["type"] == "object"


def test_missing_spec_file(temp_dir: Path):
    """Test error when spec file doesn't exist."""
    spec_file = temp_dir / "nonexistent.json"

    with pytest.raises(OpenAPIValidationError, match="not found"):
        load_openapi_spec(spec_file)


def test_invalid_json(temp_dir: Path):
    """Test error with invalid JSON."""
    spec_file = temp_dir / "openapi.json"
    spec_file.write_text("invalid json")

    with pytest.raises(OpenAPIValidationError, match="Invalid JSON"):
        load_openapi_spec(spec_file)


def test_invalid_spec_structure(temp_dir: Path):
    """Test error with invalid spec structure."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump({"not": "valid"}, f)

    with pytest.raises(OpenAPIValidationError, match="validation failed"):
        load_openapi_spec(spec_file, validate_spec=True)


def test_validate_spec_success(temp_dir: Path, minimal_openapi_30_spec: dict[str, Any]):
    """Test successful spec validation."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(minimal_openapi_30_spec, f)

    assert validate_openapi_spec(spec_file) is True


def test_validate_spec_failure(temp_dir: Path):
    """Test spec validation failure."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump({"invalid": "spec"}, f)

    with pytest.raises(OpenAPIValidationError):
        validate_openapi_spec(spec_file)


def test_skip_validation(temp_dir: Path):
    """Test loading spec without validation."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(
            {"openapi": "3.0.0", "info": {"title": "Test", "version": "1.0.0"}, "paths": {}}, f
        )

    # Should not raise even if spec is incomplete
    spec = load_openapi_spec(spec_file, validate_spec=False)
    assert spec.title == "Test"

# Made with Bob
