"""Prompt template management for simulation harness.

This module handles loading and rendering Jinja2 prompt templates.
"""

import importlib.resources
from typing import Any

from jinja2 import Environment, Template

from simulation_harness.openapi.parser import OpenAPIOperation, OpenAPISpec
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


def _load_template() -> Template:
    """Load Jinja2 template from package resources.

    Returns:
        Loaded Jinja2 template

    Raises:
        ValueError: If template file doesn't exist or is invalid
    """
    try:
        # Load template from package resources
        template_text = (
            importlib.resources.files("simulation_harness.agent.templates")
            .joinpath("simulator_system.jinja2")
            .read_text()
        )

        # Create Jinja2 environment
        env = Environment(
            autoescape=False,  # Don't escape for text templates
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Load template
        template = env.from_string(template_text)

        logger.info("Loaded prompt template from package resources")

        return template

    except Exception as e:
        logger.error(
            f"Failed to load template: {str(e)}",
            exc_info=True,
        )
        raise ValueError(f"Failed to load template: {e}") from e


def _operation_to_dict(operation: OpenAPIOperation) -> dict[str, Any]:
    """Convert OpenAPIOperation to dictionary for template.

    Args:
        operation: OpenAPI operation

    Returns:
        Dictionary representation
    """
    return {
        "method": operation.method,
        "path": operation.path,
        "operationId": operation.operation_id,
        "summary": operation.summary or "",
        "description": operation.description or "",
        "parameters": [
            {
                "name": p.get("name"),
                "in": p.get("in"),
                "required": p.get("required", False),
                "description": p.get("description", ""),
                "schema": p.get("schema", {}),
            }
            for p in operation.parameters
        ],
        "requestBody": _format_request_body(operation),
        "response_schema": operation.get_response_schema(),
    }


def _format_request_body(operation: OpenAPIOperation) -> dict[str, Any]:
    """Format request body for template.

    Args:
        operation: OpenAPI operation

    Returns:
        Formatted request body info
    """
    request_schema = operation.get_request_schema()
    if not request_schema:
        return {}

    # Get description from request_body if available
    description = ""
    if operation.request_body:
        description = operation.request_body.get("description", "")

    return {
        "description": description,
        "schema": request_schema,
    }


def render_system_prompt(
    spec: OpenAPISpec,
    operations: list[OpenAPIOperation],
    **kwargs: Any,
) -> str:
    """Render system prompt from template.

    Args:
        spec: OpenAPI specification
        operations: List of API operations
        **kwargs: Additional template variables

    Returns:
        Rendered system prompt
    """
    try:
        # Load template
        template = _load_template()

        # Prepare context
        context = {
            "api_info": {
                "title": spec.info.get("title", "API"),
                "version": spec.info.get("version", "1.0.0"),
                "description": spec.info.get("description", ""),
            },
            "operations": [_operation_to_dict(op) for op in operations],
            **kwargs,
        }

        # Render template
        rendered = template.render(**context)

        logger.debug(
            f"Rendered prompt template: operation_count={len(operations)}, "
            f"prompt_length={len(rendered)}"
        )

        return rendered

    except Exception as e:
        logger.error(
            f"Failed to render template: {str(e)}",
            exc_info=True,
        )
        raise ValueError(f"Failed to render template: {e}") from e


# Made with Bob
