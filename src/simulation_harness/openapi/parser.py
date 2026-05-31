"""OpenAPI specification parser for Simulation Harness.

This module handles parsing OpenAPI 3.0+ specifications and extracting
operations, schemas, and other relevant information.
"""

import json
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError as JSONSchemaValidationError
from openapi_spec_validator import validate
from openapi_spec_validator.validation.exceptions import ValidatorDetectError

from simulation_harness.utils.errors import OpenAPIValidationError


class OpenAPIOperation:
    """Represents a single OpenAPI operation."""

    def __init__(
        self,
        path: str,
        method: str,
        operation_id: str,
        summary: str | None,
        description: str | None,
        parameters: list[dict[str, Any]],
        request_body: dict[str, Any] | None,
        responses: dict[str, dict[str, Any]],
        tags: list[str],
    ):
        """Initialize OpenAPI operation.

        Args:
            path: API path (e.g., "/users/{id}")
            method: HTTP method (get, post, put, delete, etc.)
            operation_id: Unique operation identifier
            summary: Brief operation summary
            description: Detailed operation description
            parameters: List of operation parameters
            request_body: Request body schema
            responses: Response schemas by status code
            tags: Operation tags
        """
        self.path = path
        self.method = method.lower()
        self.operation_id = operation_id
        self.summary = summary or ""
        self.description = description or ""
        self.parameters = parameters
        self.request_body = request_body
        self.responses = responses
        self.tags = tags

    def __repr__(self) -> str:
        """String representation."""
        return f"OpenAPIOperation({self.method.upper()} {self.path})"

    def get_request_schema(self) -> dict[str, Any] | None:
        """Get request body schema if present.

        Returns:
            Request body schema or None
        """
        if not self.request_body:
            return None

        content = self.request_body.get("content", {})
        # Try application/json first
        if "application/json" in content:
            schema = content["application/json"].get("schema")
            return schema if isinstance(schema, dict) else None

        # Fall back to first available content type
        for _content_type, content_data in content.items():
            schema = content_data.get("schema")
            return schema if isinstance(schema, dict) else None

        return None

    def get_response_schema(self, status_code: str = "200") -> dict[str, Any] | None:
        """Get response schema for a status code.

        Args:
            status_code: HTTP status code (default: "200")

        Returns:
            Response schema or None
        """
        response = self.responses.get(status_code, {})
        content = response.get("content", {})

        # Try application/json first
        if "application/json" in content:
            schema = content["application/json"].get("schema")
            return schema if isinstance(schema, dict) else None

        # Fall back to first available content type
        for _content_type, content_data in content.items():
            schema = content_data.get("schema")
            return schema if isinstance(schema, dict) else None

        return None

    def get_required_parameters(self) -> list[dict[str, Any]]:
        """Get list of required parameters.

        Returns:
            List of required parameter definitions
        """
        return [p for p in self.parameters if p.get("required", False)]

    def get_optional_parameters(self) -> list[dict[str, Any]]:
        """Get list of optional parameters.

        Returns:
            List of optional parameter definitions
        """
        return [p for p in self.parameters if not p.get("required", False)]


class OpenAPISpec:
    """Represents a parsed OpenAPI specification."""

    def __init__(self, spec_dict: dict[str, Any]):
        """Initialize OpenAPI specification.

        Args:
            spec_dict: Raw OpenAPI specification dictionary
        """
        self.spec_dict = spec_dict
        self.info = spec_dict.get("info", {})
        self.servers = spec_dict.get("servers", [])
        self.paths = spec_dict.get("paths", {})
        self.components = spec_dict.get("components", {})
        self.schemas = self.components.get("schemas", {})
        self.operations: list[OpenAPIOperation] = []

        # Parse operations
        self._parse_operations()

    def _parse_operations(self) -> None:
        """Parse all operations from paths."""
        for path, path_item in self.paths.items():
            # Skip non-operation keys
            if not isinstance(path_item, dict):
                continue

            # Parse each HTTP method
            for method in ["get", "post", "put", "delete", "patch", "options", "head"]:
                if method not in path_item:
                    continue

                operation_data = path_item[method]
                if not isinstance(operation_data, dict):
                    continue

                # Extract operation details
                operation_id = operation_data.get("operationId", f"{method}_{path}")
                summary = operation_data.get("summary")
                description = operation_data.get("description")
                parameters = operation_data.get("parameters", [])
                request_body = operation_data.get("requestBody")
                responses = operation_data.get("responses", {})
                tags = operation_data.get("tags", [])

                # Create operation object
                operation = OpenAPIOperation(
                    path=path,
                    method=method,
                    operation_id=operation_id,
                    summary=summary,
                    description=description,
                    parameters=parameters,
                    request_body=request_body,
                    responses=responses,
                    tags=tags,
                )

                self.operations.append(operation)

    @property
    def title(self) -> str:
        """Get API title."""
        result = self.info.get("title", "Unknown API")
        return str(result)

    @property
    def version(self) -> str:
        """Get API version."""
        result = self.info.get("version", "0.0.0")
        return str(result)

    @property
    def description(self) -> str:
        """Get API description."""
        result = self.info.get("description", "")
        return str(result)

    def get_operation_by_id(self, operation_id: str) -> OpenAPIOperation | None:
        """Get operation by operation ID.

        Args:
            operation_id: Operation identifier

        Returns:
            OpenAPIOperation or None if not found
        """
        for operation in self.operations:
            if operation.operation_id == operation_id:
                return operation
        return None

    def get_operations_by_tag(self, tag: str) -> list[OpenAPIOperation]:
        """Get all operations with a specific tag.

        Args:
            tag: Tag name

        Returns:
            List of operations with the tag
        """
        return [op for op in self.operations if tag in op.tags]

    def get_schema(self, schema_name: str) -> dict[str, Any] | None:
        """Get schema definition by name.

        Args:
            schema_name: Schema name (from components/schemas)

        Returns:
            Schema definition or None if not found
        """
        result = self.schemas.get(schema_name)
        return result if isinstance(result, dict) else None

    def resolve_ref(self, ref: str) -> dict[str, Any] | None:
        """Resolve a $ref reference.

        Args:
            ref: Reference string (e.g., "#/components/schemas/User")

        Returns:
            Referenced object or None if not found
        """
        if not ref.startswith("#/"):
            return None

        # Split reference path
        parts = ref[2:].split("/")

        # Navigate through spec
        current: Any = self.spec_dict
        for part in parts:
            if not isinstance(current, dict):
                return None
            current = current.get(part)
            if current is None:
                return None

        return current if isinstance(current, dict) else None


def validate_openapi_dict(spec_dict: dict[str, Any]) -> None:
    """Validate an OpenAPI specification dictionary.
    
    Args:
        spec_dict: OpenAPI specification as a dictionary
        
    Raises:
        OpenAPIValidationError: If validation fails
    """
    if not isinstance(spec_dict, dict):
        raise OpenAPIValidationError("OpenAPI specification must be a dictionary")
    
    try:
        validate(spec_dict)
    except (JSONSchemaValidationError, ValidatorDetectError) as e:
        raise OpenAPIValidationError(f"OpenAPI validation failed: {e}") from e


def load_openapi_spec(spec_path: Path, validate_spec: bool = True) -> OpenAPISpec:
    """Load and parse OpenAPI specification from file.

    Args:
        spec_path: Path to OpenAPI specification file (JSON or YAML)
        validate_spec: Whether to validate the specification

    Returns:
        Parsed OpenAPISpec object

    Raises:
        OpenAPIValidationError: If specification cannot be loaded or parsed
    """
    try:
        # Load file
        with open(spec_path, encoding="utf-8") as f:
            if spec_path.suffix.lower() in [".yaml", ".yml"]:
                import yaml

                spec_dict = yaml.safe_load(f)
            else:
                spec_dict = json.load(f)

        if not isinstance(spec_dict, dict):
            raise OpenAPIValidationError("OpenAPI specification must be a dictionary")

        # Validate if requested
        if validate_spec:
            try:
                validate(spec_dict)
            except (JSONSchemaValidationError, ValidatorDetectError) as e:
                raise OpenAPIValidationError(f"OpenAPI validation failed: {e}") from e

        # Parse specification
        return OpenAPISpec(spec_dict)

    except FileNotFoundError as e:
        raise OpenAPIValidationError(f"OpenAPI specification file not found: {spec_path}") from e
    except json.JSONDecodeError as e:
        raise OpenAPIValidationError(f"Invalid JSON in OpenAPI specification: {e}") from e
    except OpenAPIValidationError:
        raise
    except Exception as e:
        raise OpenAPIValidationError(f"Failed to load OpenAPI specification: {e}") from e


def validate_openapi_spec(spec_path: Path) -> bool:
    """Validate OpenAPI specification without parsing.

    Args:
        spec_path: Path to OpenAPI specification file

    Returns:
        True if specification is valid

    Raises:
        OpenAPIValidationError: If specification is invalid
    """
    try:
        load_openapi_spec(spec_path, validate_spec=True)
        return True
    except OpenAPIValidationError:
        raise

# Made with Bob
