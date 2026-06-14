"""Tests for API request models."""

import pytest
from pydantic import ValidationError

from simulation_harness.models.requests import CreateSimulationRequest


class TestCreateSimulationRequest:
    """Tests for CreateSimulationRequest model."""

    def test_create_with_minimal_fields(self):
        """Test creating request with only required fields."""
        request = CreateSimulationRequest(
            openapi_spec={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
            },
        )

        assert request.openapi_spec["openapi"] == "3.0.0"
        assert request.regenerate_skill is False  # default value

    def test_create_with_regenerate_skill_true(self):
        """Test creating request with regenerate_skill=True."""
        request = CreateSimulationRequest(
            openapi_spec={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
            },
            regenerate_skill=True,
        )

        assert request.regenerate_skill is True

    def test_create_with_regenerate_skill_false(self):
        """Test creating request with explicit regenerate_skill=False."""
        request = CreateSimulationRequest(
            openapi_spec={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
            },
            regenerate_skill=False,
        )

        assert request.regenerate_skill is False

    def test_openapi_spec_required(self):
        """Test that openapi_spec is required."""
        with pytest.raises(ValidationError) as exc_info:
            CreateSimulationRequest()

        assert "openapi_spec" in str(exc_info.value)

    def test_openapi_spec_must_be_dict(self):
        """Test that openapi_spec must be a dictionary."""
        with pytest.raises(ValidationError) as exc_info:
            CreateSimulationRequest(openapi_spec="not a dict")

        assert "openapi_spec" in str(exc_info.value)

    def test_openapi_spec_can_be_complex(self):
        """Test that openapi_spec can contain complex nested structures."""
        complex_spec = {
            "openapi": "3.1.0",
            "info": {
                "title": "Complex API",
                "version": "2.0.0",
                "description": "A complex API spec",
            },
            "paths": {
                "/users": {
                    "get": {
                        "summary": "List users",
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
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
                                            "items": {"type": "object"},
                                        }
                                    }
                                },
                            }
                        },
                    }
                }
            },
        }

        request = CreateSimulationRequest(openapi_spec=complex_spec)

        assert request.openapi_spec == complex_spec
        assert request.openapi_spec["paths"]["/users"]["get"]["summary"] == "List users"

    def test_mcp_port_defaults_to_none(self):
        """Test that mcp_port defaults to None when not provided."""
        request = CreateSimulationRequest(
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
        )
        assert request.mcp_port is None

    def test_mcp_port_accepts_valid_port(self):
        """Test that mcp_port accepts a valid port number."""
        request = CreateSimulationRequest(
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            mcp_port=9000,
        )
        assert request.mcp_port == 9000

    def test_mcp_port_accepts_min_port(self):
        """Test that mcp_port accepts port 1."""
        request = CreateSimulationRequest(
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            mcp_port=1,
        )
        assert request.mcp_port == 1

    def test_mcp_port_accepts_max_port(self):
        """Test that mcp_port accepts port 65535."""
        request = CreateSimulationRequest(
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            mcp_port=65535,
        )
        assert request.mcp_port == 65535

    def test_mcp_port_rejects_zero(self):
        """Test that mcp_port rejects port 0."""
        with pytest.raises(ValidationError):
            CreateSimulationRequest(
                openapi_spec={
                    "openapi": "3.0.0",
                    "info": {"title": "T", "version": "1"},
                },
                mcp_port=0,
            )

    def test_mcp_port_rejects_above_65535(self):
        """Test that mcp_port rejects port > 65535."""
        with pytest.raises(ValidationError):
            CreateSimulationRequest(
                openapi_spec={
                    "openapi": "3.0.0",
                    "info": {"title": "T", "version": "1"},
                },
                mcp_port=65536,
            )


# Made with Bob
