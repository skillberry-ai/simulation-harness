"""Unit tests for OpenAPI parser."""

import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from simulation_harness.openapi.parser import (
    OpenAPISpec,
    load_openapi_spec,
    sanitize_operation_id,
    validate_openapi_spec,
)
from simulation_harness.utils.errors import OpenAPIValidationError
from collections.abc import Iterator


@pytest.fixture
def temp_dir() -> Iterator[Any]:
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
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/User"}
                            }
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
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
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


def test_load_minimal_openapi_30_spec(
    temp_dir: Path, minimal_openapi_30_spec: dict[str, Any]
) -> None:
    """Test loading minimal OpenAPI 3.0 specification."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(minimal_openapi_30_spec, f)

    spec = load_openapi_spec(spec_file)

    assert isinstance(spec, OpenAPISpec)
    assert spec.title == "Test API"
    assert spec.version == "1.0.0"
    assert len(spec.operations) == 0


def test_load_minimal_openapi_31_spec(
    temp_dir: Path, minimal_openapi_31_spec: dict[str, Any]
) -> None:
    """Test loading minimal OpenAPI 3.1 specification."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(minimal_openapi_31_spec, f)

    spec = load_openapi_spec(spec_file)

    assert isinstance(spec, OpenAPISpec)
    assert spec.title == "Test API"
    assert spec.version == "1.0.0"
    assert len(spec.operations) == 0


def test_load_full_spec(temp_dir: Path, full_openapi_spec: dict[str, Any]) -> None:
    """Test loading full OpenAPI specification with operations."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    assert spec.title == "Test API"
    assert spec.description == "A test API"
    assert len(spec.operations) == 3
    assert len(spec.servers) == 1


def test_parse_operations(temp_dir: Path, full_openapi_spec: dict[str, Any]) -> None:
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


def test_get_operation_by_id(temp_dir: Path, full_openapi_spec: dict[str, Any]) -> None:
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


def test_get_operations_by_tag(
    temp_dir: Path, full_openapi_spec: dict[str, Any]
) -> None:
    """Test getting operations by tag."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    user_operations = spec.get_operations_by_tag("users")
    assert len(user_operations) == 3


def test_operation_request_schema(
    temp_dir: Path, full_openapi_spec: dict[str, Any]
) -> None:
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


def test_operation_response_schema(
    temp_dir: Path, full_openapi_spec: dict[str, Any]
) -> None:
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


def test_operation_parameters(
    temp_dir: Path, full_openapi_spec: dict[str, Any]
) -> None:
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


def test_path_item_level_parameters_merged_into_each_operation() -> None:
    """Path-item-level parameters apply to every operation under the path.

    A shared ``{id}`` path parameter declared once at the path-item level must
    reach every method (get/delete/...), not just an operation that redeclares
    it — otherwise the generated tool schema omits the path parameter.
    """
    spec = _spec_with_operation_ids(
        {
            "/tasks/{id}": {
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    },
                ],
                "get": {"operationId": "getTask", "responses": {}},
                "delete": {"operationId": "deleteTask", "responses": {}},
            }
        }
    )

    for op_id in ("getTask", "deleteTask"):
        op = spec.get_operation_by_id(op_id)
        assert op is not None, op_id
        assert [p["name"] for p in op.parameters] == ["id"]
        assert [p["name"] for p in op.get_required_parameters()] == ["id"]


def test_operation_level_parameter_overrides_path_level() -> None:
    """An operation-level parameter overrides a path-level one on (name, in)."""
    spec = _spec_with_operation_ids(
        {
            "/tasks/{id}": {
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "path-level",
                    },
                ],
                "get": {
                    "operationId": "getTask",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                            "description": "op-level",
                        },
                        {
                            "name": "verbose",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "boolean"},
                        },
                    ],
                    "responses": {},
                },
            }
        }
    )

    op = spec.get_operation_by_id("getTask")
    assert op is not None
    # No duplicate 'id'; op-level entry wins; new query param appended.
    assert [p["name"] for p in op.parameters] == ["id", "verbose"]
    by_name = {p["name"]: p for p in op.parameters}
    assert by_name["id"]["schema"]["type"] == "integer"
    assert by_name["id"]["description"] == "op-level"


def test_get_schema(temp_dir: Path, full_openapi_spec: dict[str, Any]) -> None:
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


def test_resolve_ref(temp_dir: Path, full_openapi_spec: dict[str, Any]) -> None:
    """Test resolving $ref references."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(full_openapi_spec, f)

    spec = load_openapi_spec(spec_file)

    resolved = spec.resolve_ref("#/components/schemas/User")
    assert resolved is not None
    assert resolved["type"] == "object"


def test_missing_spec_file(temp_dir: Path) -> None:
    """Test error when spec file doesn't exist."""
    spec_file = temp_dir / "nonexistent.json"

    with pytest.raises(OpenAPIValidationError, match="not found"):
        load_openapi_spec(spec_file)


def test_invalid_json(temp_dir: Path) -> None:
    """Test error with invalid JSON."""
    spec_file = temp_dir / "openapi.json"
    spec_file.write_text("invalid json")

    with pytest.raises(OpenAPIValidationError, match="Invalid JSON"):
        load_openapi_spec(spec_file)


def test_invalid_spec_structure(temp_dir: Path) -> None:
    """Test error with invalid spec structure."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump({"not": "valid"}, f)

    with pytest.raises(OpenAPIValidationError, match="validation failed"):
        load_openapi_spec(spec_file, validate_spec=True)


def test_validate_spec_success(
    temp_dir: Path, minimal_openapi_30_spec: dict[str, Any]
) -> None:
    """Test successful spec validation."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(minimal_openapi_30_spec, f)

    assert validate_openapi_spec(spec_file) is True


def test_validate_spec_failure(temp_dir: Path) -> None:
    """Test spec validation failure."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump({"invalid": "spec"}, f)

    with pytest.raises(OpenAPIValidationError):
        validate_openapi_spec(spec_file)


def test_skip_validation(temp_dir: Path) -> None:
    """Test loading spec without validation."""
    spec_file = temp_dir / "openapi.json"
    with open(spec_file, "w") as f:
        json.dump(
            {
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
                "paths": {},
            },
            f,
        )

    # Should not raise even if spec is incomplete
    spec = load_openapi_spec(spec_file, validate_spec=False)
    assert spec.title == "Test"


def _spec_with_operation_ids(paths: dict[str, Any]) -> OpenAPISpec:
    """Build an OpenAPISpec directly from a paths mapping."""
    return OpenAPISpec(
        {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": paths,
        }
    )


class TestSanitizeOperationId:
    """Unit tests for sanitize_operation_id."""

    def test_path_style_id_becomes_underscore_separated(self) -> None:
        result = sanitize_operation_id(
            "/accommodations/search", method="post", path="/accommodations/search"
        )
        assert result == "accommodations_search"

    def test_leading_and_trailing_separators_stripped(self) -> None:
        result = sanitize_operation_id(
            "orders/preview", method="post", path="/orders/preview"
        )
        assert result == "orders_preview"

    def test_already_valid_id_unchanged(self) -> None:
        result = sanitize_operation_id("getUser", method="get", path="/users/{id}")
        assert result == "getUser"

    def test_hyphen_and_underscore_preserved(self) -> None:
        result = sanitize_operation_id("list_users-v2", method="get", path="/users")
        assert result == "list_users-v2"

    def test_empty_id_falls_back_to_method_and_path(self) -> None:
        result = sanitize_operation_id("", method="get", path="/users/{id}")
        assert result == "get_users_id"

    def test_all_invalid_id_falls_back_to_method_and_path(self) -> None:
        result = sanitize_operation_id("/", method="get", path="/users/{id}")
        assert result == "get_users_id"

    def test_result_is_valid_mcp_tool_name(self) -> None:
        result = sanitize_operation_id(
            "/common/locations/airports",
            method="post",
            path="/common/locations/airports",
        )
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", result)

    def test_length_capped_at_64(self) -> None:
        long_raw = "/" + "/".join(["segment"] * 20)
        result = sanitize_operation_id(long_raw, method="get", path=long_raw)
        assert len(result) <= 64
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", result)


class TestParserSanitizesOperationIds:
    """Integration: the parser sanitizes operationIds when building operations."""

    def test_slash_operation_ids_are_sanitized(self) -> None:
        spec = _spec_with_operation_ids(
            {
                "/accommodations/search": {
                    "post": {"operationId": "/accommodations/search", "responses": {}}
                },
                "/orders/preview": {
                    "post": {"operationId": "orders/preview", "responses": {}}
                },
            }
        )

        ids = [op.operation_id for op in spec.operations]
        assert ids == ["accommodations_search", "orders_preview"]
        assert all("/" not in oid for oid in ids)

    def test_get_operation_by_id_uses_sanitized_id(self) -> None:
        spec = _spec_with_operation_ids(
            {
                "/accommodations/search": {
                    "post": {"operationId": "/accommodations/search", "responses": {}}
                }
            }
        )

        op = spec.get_operation_by_id("accommodations_search")
        assert op is not None
        assert op.path == "/accommodations/search"
        assert op.method == "post"

    def test_colliding_ids_are_disambiguated(self) -> None:
        spec = _spec_with_operation_ids(
            {
                "/a": {"post": {"operationId": "foo/bar", "responses": {}}},
                "/b": {"post": {"operationId": "foo bar", "responses": {}}},
            }
        )

        ids = [op.operation_id for op in spec.operations]
        assert ids == ["foo_bar", "foo_bar_2"]
        assert len(set(ids)) == len(ids)

    def test_missing_operation_id_sanitized_fallback(self) -> None:
        spec = _spec_with_operation_ids({"/users/{id}": {"get": {"responses": {}}}})

        ids = [op.operation_id for op in spec.operations]
        assert ids == ["get_users_id"]


# Made with Bob
