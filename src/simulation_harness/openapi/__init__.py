"""OpenAPI parsing and tool generation for Simulation Harness.

This package provides utilities for parsing OpenAPI specifications and
generating tool definitions from them.
"""

from .parser import (
    OpenAPIOperation,
    OpenAPISpec,
    load_openapi_spec,
    validate_openapi_spec,
)
from .schema_validator import (
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
from .tool_generator import (
    ToolGenerationError,
    generate_tool_from_operation,
    generate_tools_from_spec,
    get_optional_parameters,
    get_required_parameters,
    get_tool_by_name,
)

__all__ = [
    # Parser
    "OpenAPIOperation",
    "OpenAPISpec",
    "load_openapi_spec",
    "validate_openapi_spec",
    # Schema Validator
    "SchemaValidationError",
    "check_required_fields",
    "get_array_item_schema",
    "get_property_schema",
    "get_schema_type",
    "is_array_schema",
    "is_object_schema",
    "validate_against_schema",
    "validate_request_body",
    "validate_response",
    # Tool Generator
    "ToolGenerationError",
    "generate_tool_from_operation",
    "generate_tools_from_spec",
    "get_optional_parameters",
    "get_required_parameters",
    "get_tool_by_name",
]

# Made with Bob
