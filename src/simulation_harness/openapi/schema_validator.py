"""Schema validation utilities for OpenAPI specifications."""

from typing import Any

from jsonschema import Draft7Validator


class SchemaValidationError(Exception):
    """Raised when schema validation fails."""

    pass


def validate_against_schema(data: Any, schema: dict[str, Any], strict: bool = False) -> list[str]:
    """Validate data against a JSON schema.

    Args:
        data: Data to validate
        schema: JSON schema to validate against
        strict: If True, raise exception on validation errors

    Returns:
        List of validation error messages (empty if valid)

    Raises:
        SchemaValidationError: If strict=True and validation fails
    """
    # Create validator
    validator = Draft7Validator(schema)

    # Collect errors
    errors = []
    for error in validator.iter_errors(data):
        error_path = ".".join(str(p) for p in error.path) if error.path else "root"
        error_msg = f"{error_path}: {error.message}"
        errors.append(error_msg)

    # Raise if strict mode
    if strict and errors:
        raise SchemaValidationError(f"Schema validation failed: {'; '.join(errors)}")

    return errors


def validate_request_body(
    body: dict[str, Any], operation_schema: dict[str, Any] | None, strict: bool = False
) -> list[str]:
    """Validate request body against operation schema.

    Args:
        body: Request body data
        operation_schema: Request body schema from OpenAPI operation
        strict: If True, raise exception on validation errors

    Returns:
        List of validation error messages (empty if valid)

    Raises:
        SchemaValidationError: If strict=True and validation fails
    """
    if operation_schema is None:
        return []

    return validate_against_schema(body, operation_schema, strict=strict)


def validate_response(
    response: Any, operation_schema: dict[str, Any] | None, strict: bool = False
) -> list[str]:
    """Validate response against operation schema.

    Args:
        response: Response data
        operation_schema: Response schema from OpenAPI operation
        strict: If True, raise exception on validation errors

    Returns:
        List of validation error messages (empty if valid)

    Raises:
        SchemaValidationError: If strict=True and validation fails
    """
    if operation_schema is None:
        return []

    return validate_against_schema(response, operation_schema, strict=strict)


def check_required_fields(data: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Check if all required fields are present in data.

    Args:
        data: Data to check
        schema: JSON schema with required fields

    Returns:
        List of missing required field names
    """
    required = schema.get("required", [])
    missing = []

    for field in required:
        if field not in data:
            missing.append(field)

    return missing


def get_schema_type(schema: dict[str, Any]) -> str | None:
    """Get the type of a schema.

    Args:
        schema: JSON schema

    Returns:
        Schema type (string, object, array, etc.) or None
    """
    return schema.get("type")


def is_object_schema(schema: dict[str, Any]) -> bool:
    """Check if schema represents an object.

    Args:
        schema: JSON schema

    Returns:
        True if schema is an object type
    """
    return get_schema_type(schema) == "object"


def is_array_schema(schema: dict[str, Any]) -> bool:
    """Check if schema represents an array.

    Args:
        schema: JSON schema

    Returns:
        True if schema is an array type
    """
    return get_schema_type(schema) == "array"


def get_property_schema(schema: dict[str, Any], property_name: str) -> dict[str, Any] | None:
    """Get schema for a specific property.

    Args:
        schema: Object schema
        property_name: Property name

    Returns:
        Property schema or None if not found
    """
    if not is_object_schema(schema):
        return None

    properties = schema.get("properties", {})
    result = properties.get(property_name)
    return result if isinstance(result, dict) else None


def get_array_item_schema(schema: dict[str, Any]) -> dict[str, Any] | None:
    """Get schema for array items.

    Args:
        schema: Array schema

    Returns:
        Item schema or None if not an array
    """
    if not is_array_schema(schema):
        return None

    return schema.get("items")

# Made with Bob
