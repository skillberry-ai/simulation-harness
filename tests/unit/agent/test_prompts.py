"""Tests for prompts module."""

import pytest
from unittest.mock import Mock
from simulation_harness.agent.prompts import render_system_prompt
from simulation_harness.openapi.parser import OpenAPISpec, OpenAPIOperation


@pytest.fixture
def mock_spec():
    """Create a mock OpenAPI spec."""
    spec = Mock(spec=OpenAPISpec)
    spec.info = {
        "title": "Test API",
        "version": "1.0.0",
        "description": "A test API"
    }
    spec.servers = [{"url": "https://api.example.com"}]
    return spec


@pytest.fixture
def mock_operation():
    """Create a mock OpenAPI operation."""
    op = Mock(spec=OpenAPIOperation)
    op.method = "get"
    op.path = "/users/{id}"
    op.operation_id = "getUser"
    op.summary = "Get user by ID"
    op.description = "Retrieves a user by their ID"
    op.parameters = [
        {
            "name": "id",
            "in": "path",
            "required": True,
            "description": "User ID",
            "schema": {"type": "string"}
        }
    ]
    op.request_body = None
    op.get_request_schema = Mock(return_value=None)
    op.get_response_schema = Mock(return_value={
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"}
        }
    })
    return op


def test_render_system_prompt_basic(mock_spec, mock_operation):
    """Test rendering system prompt with basic operation."""
    result = render_system_prompt(mock_spec, [mock_operation])
    
    # Check that key elements are in the prompt
    assert "Test API" in result
    assert "1.0.0" in result
    assert "GET /users/{id}" in result
    assert "getUser" in result
    assert "Get user by ID" in result


def test_render_system_prompt_multiple_operations(mock_spec, mock_operation):
    """Test rendering system prompt with multiple operations."""
    op2 = Mock(spec=OpenAPIOperation)
    op2.method = "post"
    op2.path = "/users"
    op2.operation_id = "createUser"
    op2.summary = "Create user"
    op2.description = "Creates a new user"
    op2.parameters = []
    op2.request_body = {
        "description": "User data",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"}
                    }
                }
            }
        }
    }
    op2.get_request_schema = Mock(return_value={
        "type": "object",
        "properties": {
            "name": {"type": "string"}
        }
    })
    op2.get_response_schema = Mock(return_value={
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"}
        }
    })
    
    result = render_system_prompt(mock_spec, [mock_operation, op2])
    
    # Check both operations are in the prompt
    assert "GET /users/{id}" in result
    assert "POST /users" in result
    assert "getUser" in result
    assert "createUser" in result


def test_render_system_prompt_empty_operations(mock_spec):
    """Test rendering system prompt with no operations."""
    result = render_system_prompt(mock_spec, [])
    
    # Should still have API info
    assert "Test API" in result
    assert "1.0.0" in result


def test_render_system_prompt_includes_instructions(mock_spec, mock_operation):
    """Test that system prompt includes key instructions."""
    result = render_system_prompt(mock_spec, [mock_operation])
    
    # Check for key instruction phrases
    assert "simulate" in result.lower() or "simulating" in result.lower()
    assert "json" in result.lower()
    assert "consistent" in result.lower() or "consistency" in result.lower()

# Made with Bob
