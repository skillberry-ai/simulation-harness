"""Tests for the prompts module."""

from unittest.mock import Mock

from simulation_harness.agent.prompts import render_system_prompt
from simulation_harness.openapi.parser import OpenAPISpec


def _mock_spec():
    spec = Mock(spec=OpenAPISpec)
    spec.info = {"title": "Test API", "version": "1.0.0", "description": "A test API"}
    spec.servers = [{"url": "https://api.example.com"}]
    return spec


def test_render_includes_api_info():
    result = render_system_prompt(_mock_spec())
    assert "Test API" in result
    assert "1.0.0" in result


def test_render_keeps_state_mechanism_and_json_contract():
    result = render_system_prompt(_mock_spec())
    # State tools must still be described in the always-on prompt.
    assert "state_get" in result
    assert "state_insert" in result
    assert "where" in result.lower()
    # JSON-only contract preserved.
    assert "json" in result.lower()


def test_render_points_to_simulation_skill():
    result = render_system_prompt(_mock_spec())
    assert "skill" in result.lower()


def test_render_does_not_embed_per_operation_detail():
    # render_system_prompt no longer accepts or renders operations.
    result = render_system_prompt(_mock_spec())
    assert "/users/{id}" not in result
    assert "getUser" not in result
