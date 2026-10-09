"""Tests for the prompts module."""

from pathlib import Path
from unittest.mock import Mock

from simulation_harness.agent.prompts import render_system_prompt
from simulation_harness.openapi.parser import OpenAPISpec
from unittest.mock import MagicMock


def _mock_spec() -> MagicMock:
    spec = Mock(spec=OpenAPISpec)
    spec.info = {"title": "Test API", "version": "1.0.0", "description": "A test API"}
    spec.servers = [{"url": "https://api.example.com"}]
    return spec


def test_render_includes_api_info() -> None:
    result = render_system_prompt(_mock_spec())
    assert "Test API" in result
    assert "1.0.0" in result


def test_render_keeps_state_mechanism_and_json_contract() -> None:
    result = render_system_prompt(_mock_spec())
    # State tools must still be described in the always-on prompt.
    assert "state_get" in result
    assert "state_insert" in result
    assert "where" in result.lower()
    # JSON-only contract preserved.
    assert "json" in result.lower()


def test_render_points_to_simulation_skill() -> None:
    result = render_system_prompt(_mock_spec())
    assert "skill" in result.lower()


def test_render_does_not_embed_per_operation_detail() -> None:
    # render_system_prompt no longer accepts or renders operations.
    result = render_system_prompt(_mock_spec())
    assert "/users/{id}" not in result
    assert "getUser" not in result


_GOLDEN = (
    Path(__file__).parents[2]
    / "fixtures"
    / "prompts"
    / "simulator_system_generative.txt"
)


def test_generative_render_is_unchanged_from_pre_fidelity_prompt() -> None:
    rendered = render_system_prompt(_mock_spec(), fidelity="generative")
    assert rendered.rstrip("\n") == _GOLDEN.read_text().rstrip("\n")


def test_default_fidelity_is_generative() -> None:
    assert render_system_prompt(_mock_spec()) == render_system_prompt(
        _mock_spec(), fidelity="generative"
    )


def test_strict_render_drops_realism_guidance() -> None:
    strict = render_system_prompt(_mock_spec(), fidelity="strict")
    assert "Generate plausible data appropriate to the domain" not in strict
    assert "## Data Generation Guidelines" not in strict
    assert "**Be realistic**" not in strict


def test_strict_render_carries_closed_world_rules() -> None:
    strict = render_system_prompt(_mock_spec(), fidelity="strict")
    assert "## Closed-World Data" in strict
    assert "## Format Conventions" in strict
    assert "empty-result" in strict
    assert '"read_only"' in strict
    assert "On-Demand Generation Rules (generative mode only)" in strict
    # Shared guidance survives in both modes.
    assert "Never fabricate data from memory" in strict
    assert "state_get" in strict


def test_generative_render_has_no_closed_world_section() -> None:
    generative = render_system_prompt(_mock_spec(), fidelity="generative")
    assert "## Closed-World Data" not in generative
