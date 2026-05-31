"""Unit tests for schema validation utilities."""

import pytest

from simulation_harness.openapi.schema_validator import (
    SchemaValidationError,
    check_required_fields,
    get_array_item_schema,
    get_property_schema,
    get_schema_type,
    is_array_schema,
    is_object_schema,
    validate_against_schema,
    validate_request_body,
    validate_response,
)


def test_validate_against_schema_valid():
    """Test validating valid data against schema."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }

    data = {"name": "John", "age": 30}
    errors = validate_against_schema(data, schema)

    assert len(errors) == 0


def test_validate_against_schema_missing_required():
    """Test validation with missing required field."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name"],
    }

    data = {"age": 30}  # Missing required "name"
    errors = validate_against_schema(data, schema)

    assert len(errors) > 0
    assert any("name" in error.lower() for error in errors)


def test_validate_against_schema_wrong_type():
    """Test validation with wrong data type."""
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}}

    data = {"age": "not a number"}
    errors = validate_against_schema(data, schema)

    assert len(errors) > 0


def test_validate_against_schema_strict_mode():
    """Test strict mode raises exception on validation errors."""
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}

    data = {}  # Missing required field

    with pytest.raises(SchemaValidationError, match="validation failed"):
        validate_against_schema(data, schema, strict=True)


def test_validate_request_body_valid():
    """Test validating valid request body."""
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}

    body = {"name": "John"}
    errors = validate_request_body(body, schema)

    assert len(errors) == 0


def test_validate_request_body_no_schema():
    """Test validating request body with no schema."""
    errors = validate_request_body({"data": "value"}, None)
    assert len(errors) == 0


def test_validate_response_valid():
    """Test validating valid response."""
    schema = {"type": "array", "items": {"type": "string"}}

    response = ["item1", "item2"]
    errors = validate_response(response, schema)

    assert len(errors) == 0


def test_validate_response_no_schema():
    """Test validating response with no schema."""
    errors = validate_response({"data": "value"}, None)
    assert len(errors) == 0


def test_check_required_fields_all_present():
    """Test checking required fields when all are present."""
    schema = {"required": ["name", "email"]}
    data = {"name": "John", "email": "john@example.com", "age": 30}

    missing = check_required_fields(data, schema)
    assert len(missing) == 0


def test_check_required_fields_some_missing():
    """Test checking required fields when some are missing."""
    schema = {"required": ["name", "email"]}
    data = {"name": "John"}

    missing = check_required_fields(data, schema)
    assert "email" in missing
    assert "name" not in missing


def test_get_schema_type():
    """Test getting schema type."""
    assert get_schema_type({"type": "object"}) == "object"
    assert get_schema_type({"type": "array"}) == "array"
    assert get_schema_type({"type": "string"}) == "string"
    assert get_schema_type({}) is None


def test_is_object_schema():
    """Test checking if schema is object type."""
    assert is_object_schema({"type": "object"}) is True
    assert is_object_schema({"type": "array"}) is False
    assert is_object_schema({}) is False


def test_is_array_schema():
    """Test checking if schema is array type."""
    assert is_array_schema({"type": "array"}) is True
    assert is_array_schema({"type": "object"}) is False
    assert is_array_schema({}) is False


def test_get_property_schema():
    """Test getting property schema from object schema."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    }

    name_schema = get_property_schema(schema, "name")
    assert name_schema is not None
    assert name_schema["type"] == "string"

    age_schema = get_property_schema(schema, "age")
    assert age_schema is not None
    assert age_schema["type"] == "integer"

    # Non-existent property
    assert get_property_schema(schema, "nonexistent") is None


def test_get_property_schema_non_object():
    """Test getting property schema from non-object schema."""
    schema = {"type": "array"}
    assert get_property_schema(schema, "name") is None


def test_get_array_item_schema():
    """Test getting array item schema."""
    schema = {"type": "array", "items": {"type": "string"}}

    item_schema = get_array_item_schema(schema)
    assert item_schema is not None
    assert item_schema["type"] == "string"


def test_get_array_item_schema_non_array():
    """Test getting array item schema from non-array schema."""
    schema = {"type": "object"}
    assert get_array_item_schema(schema) is None

# Made with Bob
