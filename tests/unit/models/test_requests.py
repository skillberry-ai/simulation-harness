"""Tests for API request models."""

import pytest
from pydantic import ValidationError

from simulation_harness.models.requests import (
    CreateSimulationRequest,
    StartSimulationRequest,
)


class TestCreateSimulationRequest:
    """Tests for CreateSimulationRequest model."""

    def test_create_with_minimal_fields(self) -> None:
        """Test creating request with only required fields."""
        request = CreateSimulationRequest(
            openapi_spec={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
            },
        )

        assert request.openapi_spec["openapi"] == "3.0.0"
        assert request.regenerate_skill is False  # default value

    def test_create_with_regenerate_skill_true(self) -> None:
        """Test creating request with regenerate_skill=True."""
        request = CreateSimulationRequest(
            openapi_spec={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
            },
            regenerate_skill=True,
        )

        assert request.regenerate_skill is True

    def test_create_with_regenerate_skill_false(self) -> None:
        """Test creating request with explicit regenerate_skill=False."""
        request = CreateSimulationRequest(
            openapi_spec={
                "openapi": "3.0.0",
                "info": {"title": "Test", "version": "1.0.0"},
            },
            regenerate_skill=False,
        )

        assert request.regenerate_skill is False

    def test_openapi_spec_required(self) -> None:
        """Test that openapi_spec is required."""
        with pytest.raises(ValidationError) as exc_info:
            CreateSimulationRequest()  # type: ignore[call-arg]

        assert "openapi_spec" in str(exc_info.value)

    def test_openapi_spec_must_be_dict(self) -> None:
        """Test that openapi_spec must be a dictionary."""
        with pytest.raises(ValidationError) as exc_info:
            CreateSimulationRequest(openapi_spec="not a dict")

        assert "openapi_spec" in str(exc_info.value)

    def test_openapi_spec_can_be_complex(self) -> None:
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

    def test_mcp_port_defaults_to_none(self) -> None:
        """Test that mcp_port defaults to None when not provided."""
        request = CreateSimulationRequest(
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
        )
        assert request.mcp_port is None

    def test_mcp_port_accepts_valid_port(self) -> None:
        """Test that mcp_port accepts a valid port number."""
        request = CreateSimulationRequest(
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            mcp_port=9000,
        )
        assert request.mcp_port == 9000

    def test_mcp_port_accepts_min_port(self) -> None:
        """Test that mcp_port accepts port 1."""
        request = CreateSimulationRequest(
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            mcp_port=1,
        )
        assert request.mcp_port == 1

    def test_mcp_port_accepts_max_port(self) -> None:
        """Test that mcp_port accepts port 65535."""
        request = CreateSimulationRequest(
            openapi_spec={"openapi": "3.0.0", "info": {"title": "T", "version": "1"}},
            mcp_port=65535,
        )
        assert request.mcp_port == 65535

    def test_mcp_port_rejects_zero(self) -> None:
        """Test that mcp_port rejects port 0."""
        with pytest.raises(ValidationError):
            CreateSimulationRequest(
                openapi_spec={
                    "openapi": "3.0.0",
                    "info": {"title": "T", "version": "1"},
                },
                mcp_port=0,
            )

    def test_mcp_port_rejects_above_65535(self) -> None:
        """Test that mcp_port rejects port > 65535."""
        with pytest.raises(ValidationError):
            CreateSimulationRequest(
                openapi_spec={
                    "openapi": "3.0.0",
                    "info": {"title": "T", "version": "1"},
                },
                mcp_port=65536,
            )


class TestUnknownFieldsAreRejected:
    """Both request models forbid extra fields.

    pydantic's default is extra="ignore", which drops an unknown key and leaves
    the corresponding field at its default -- so a misspelled flag produces a
    successful request that quietly did something else. The regression this
    guards is real: `regenerate: true` (the field is `regenerate_skill`) made a
    determinism check reuse a cached skill on every run and still report success.
    """

    MINIMAL_SPEC = {"openapi": "3.0.0", "info": {"title": "T", "version": "1"}}

    def test_create_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateSimulationRequest(
                openapi_spec=self.MINIMAL_SPEC,
                regenerate=True,  # type: ignore[call-arg]
            )

        assert "regenerate" in str(exc_info.value)

    def test_create_names_the_offending_field(self) -> None:
        """The error must identify the key, so the fix is obvious."""
        with pytest.raises(ValidationError) as exc_info:
            CreateSimulationRequest(
                openapi_spec=self.MINIMAL_SPEC,
                totally_made_up=1,  # type: ignore[call-arg]
            )

        errors = exc_info.value.errors()
        assert any(
            e["type"] == "extra_forbidden" and e["loc"] == ("totally_made_up",)
            for e in errors
        ), errors

    def test_start_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            StartSimulationRequest(
                name="some-skill",
                regenerate_skill=True,  # type: ignore[call-arg]
            )

        assert "regenerate_skill" in str(exc_info.value)

    def test_known_fields_still_accepted(self) -> None:
        """Strictness must not narrow the real surface."""
        request = CreateSimulationRequest(
            openapi_spec=self.MINIMAL_SPEC,
            name="sim",
            regenerate_skill=True,
            mcp_port=9100,
        )

        assert request.name == "sim"
        assert request.regenerate_skill is True
        assert request.mcp_port == 9100

    def test_arbitrary_keys_inside_openapi_spec_still_allowed(self) -> None:
        """forbid applies to the request body, not to the spec it carries.

        An OpenAPI document is an arbitrary nested dict, vendor extensions
        included; rejecting unknown keys there would break every real spec.
        """
        spec = dict(self.MINIMAL_SPEC)
        spec["x-vendor-extension"] = {"anything": ["at", "all"]}
        spec["paths"] = {"/t": {"get": {"responses": {"200": {"description": "ok"}}}}}

        request = CreateSimulationRequest(openapi_spec=spec)

        assert request.openapi_spec["x-vendor-extension"] == {"anything": ["at", "all"]}


# Made with Bob
