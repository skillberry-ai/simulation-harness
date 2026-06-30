"""Prompt template management for simulation harness.

This module handles loading and rendering Jinja2 prompt templates.
"""

import importlib.resources
from typing import Any

from jinja2 import Environment, Template

from simulation_harness.openapi.parser import OpenAPISpec
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
        env = Environment(  # nosec B701 - renders plain-text LLM prompts, not HTML; autoescaping would corrupt prompt content
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


def render_system_prompt(
    spec: OpenAPISpec,
    **kwargs: Any,
) -> str:
    """Render the simulator system prompt from the template.

    Per-operation detail is no longer rendered here; it is loaded at runtime
    from the simulation skill. This prompt carries the simulator role, API
    info, the state mechanism, the JSON contract, and a pointer to the skill.

    Args:
        spec: OpenAPI specification
        **kwargs: Additional template variables

    Returns:
        Rendered system prompt
    """
    try:
        template = _load_template()

        context = {
            "api_info": {
                "title": spec.info.get("title", "API"),
                "version": spec.info.get("version", "1.0.0"),
                "description": spec.info.get("description", ""),
            },
            **kwargs,
        }

        rendered = template.render(**context)

        logger.debug(f"Rendered prompt template: prompt_length={len(rendered)}")

        return rendered

    except Exception as e:
        logger.error(f"Failed to render template: {str(e)}", exc_info=True)
        raise ValueError(f"Failed to render template: {e}") from e


# Made with Bob
