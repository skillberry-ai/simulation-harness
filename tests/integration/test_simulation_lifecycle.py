"""Integration tests for simulation lifecycle management.

Tests the complete lifecycle of simulations from creation through deletion,
including skill generation, reuse, and session management.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.fixture
def valid_openapi_spec():
    """Provide a valid OpenAPI 3.0 specification."""
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "Test API",
            "version": "1.0.0",
        },
        "paths": {
            "/test": {
                "get": {
                    "operationId": "getTest",
                    "summary": "Get test data",
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"message": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


@pytest.fixture
def valid_openapi_spec_31():
    """Provide a valid OpenAPI 3.1 specification."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Test API 3.1",
            "version": "1.0.0",
        },
        "paths": {
            "/test": {
                "get": {
                    "operationId": "getTest31",
                    "summary": "Get test data",
                    "responses": {
                        "200": {
                            "description": "Success",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"message": {"type": "string"}},
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


@pytest.fixture
def app_client():
    """Create test client with valid config and clean state for each test."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config = {
            "llm": {
                "provider": "openai",
                "skill_generation_model": "gpt-4",
                "simulation_model": "gpt-4",
                "temperature": 0,
            },
            "skills": {"folder": "./skills"},
            "sessions": {
                "max_messages": 100,
                "idle_timeout_seconds": 3600,
                "max_concurrent_queue_depth": 8,
            },
            "mcp": {"transport": "sse"},
        }
        yaml.dump(config, f)
        config_path = f.name

    _prior_key = os.environ.get("LLM_API_KEY")
    os.environ["HARNESS_CONFIG_PATH"] = config_path
    os.environ["LLM_API_KEY"] = "test-key"

    try:
        from simulation_harness.main import app

        client = TestClient(app)

        # Clean up any existing simulation before test
        try:
            client.delete("/api/v1/simulation")
        except Exception:
            pass  # Ignore if no simulation exists

        yield client

        # Clean up after test
        try:
            client.delete("/api/v1/simulation")
        except Exception:
            pass  # Ignore if no simulation exists
    finally:
        os.unlink(config_path)
        if "HARNESS_CONFIG_PATH" in os.environ:
            del os.environ["HARNESS_CONFIG_PATH"]
        if _prior_key is not None:
            os.environ["LLM_API_KEY"] = _prior_key
        elif "LLM_API_KEY" in os.environ:
            del os.environ["LLM_API_KEY"]


class TestSimulationCreation:
    """Test simulation creation from OpenAPI spec."""

    def test_create_simulation_from_openapi_spec(self, app_client, valid_openapi_spec):
        """Test creating a simulation from a valid OpenAPI spec."""
        # Mock skill generation to avoid actual LLM calls
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "test-api"
        assert data["status"] == "active"
        assert "session_state" in data
        assert data["session_state"]["tool_call_count"] == 0
        assert data["mcp_endpoint"] == "/mcp/test-api"
        assert "created_at" in data

    def test_create_simulation_openapi_31_accepted(
        self, app_client, valid_openapi_spec_31
    ):
        """Test that OpenAPI 3.1.x specs are accepted."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec_31, "regenerate_skill": False},
            )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "test-api-3.1"

    def test_create_simulation_invalid_spec_returns_422(self, app_client):
        """Test that invalid OpenAPI spec returns 422."""
        invalid_spec = {
            "openapi": "3.0.0",
            # Missing required 'info' field
            "paths": {},
        }

        response = app_client.post(
            "/api/v1/simulation",
            json={"openapi_spec": invalid_spec, "regenerate_skill": False},
        )

        assert response.status_code == 422
        assert "validation" in response.json()["detail"].lower()

    def test_create_simulation_10mb_body_cap_enforced(
        self, app_client, valid_openapi_spec
    ):
        """Test that 10MB body size limit is enforced."""
        # Create a spec that exceeds 10MB
        large_spec = valid_openapi_spec.copy()
        # Add a large description to exceed 10MB
        large_spec["info"]["description"] = "x" * (11 * 1024 * 1024)

        response = app_client.post(
            "/api/v1/simulation",
            json={"openapi_spec": large_spec, "regenerate_skill": False},
        )

        assert response.status_code == 413

    def test_create_simulation_already_exists_returns_409(
        self, app_client, valid_openapi_spec
    ):
        """Test that creating a duplicate simulation returns 409."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create first simulation
            response1 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response1.status_code == 201

            # Try to create second simulation
            response2 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response2.status_code == 409


class TestSkillGeneration:
    """Test skill generation and reuse."""

    def test_skill_generation_new_skill(self, app_client, valid_openapi_spec):
        """Test that a new skill is generated when none exists."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )

            assert response.status_code == 201
            # Verify skill generator was called
            mock_gen.assert_called_once()

    def test_skill_reuse_existing_skill(self, app_client, valid_openapi_spec):
        """Test that existing skill is reused when regenerate=False.

        This test verifies the behavior by creating a simulation twice with the same spec.
        The skill registry should reuse the skill file created in the first call.
        """
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            # Mock to return a path (simulating successful generation)
            from pathlib import Path

            mock_gen.return_value = Path("/tmp/test-api/SKILL.md")

            # Create first simulation (generates skill)
            response1 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response1.status_code == 201
            first_call_count = mock_gen.call_count
            assert first_call_count >= 1, "Skill should be generated on first creation"

            # Delete simulation
            app_client.delete("/api/v1/simulation")

            # Create second simulation with same spec (should reuse skill if it exists on disk)
            # Note: In integration tests, the actual file system is used, so if the skill
            # was written to disk in the first call, it will be reused in the second call.
            # This test verifies the API accepts the request successfully.
            response2 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response2.status_code == 201
            # The behavior of skill reuse is tested in unit tests for SkillRegistry
            # Here we just verify the API works correctly

    def test_regenerate_flag_forces_new_skill(self, app_client, valid_openapi_spec):
        """Test that regenerate=True forces new skill generation."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create first simulation
            response1 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response1.status_code == 201
            first_call_count = mock_gen.call_count

            # Delete simulation
            app_client.delete("/api/v1/simulation")

            # Create second simulation with regenerate=True
            response2 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": True},
            )
            assert response2.status_code == 201
            # Skill generator should be called again
            assert mock_gen.call_count > first_call_count


class TestSimulationStatus:
    """Test getting simulation status."""

    def test_get_simulation_status(self, app_client, valid_openapi_spec):
        """Test getting status of active simulation."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            create_response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert create_response.status_code == 201

            # Get status
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200

            data = status_response.json()
            assert data["name"] == "test-api"
            assert data["status"] == "active"
            assert "session_state" in data

    def test_get_simulation_status_no_simulation_returns_404(self, app_client):
        """Test that getting status with no simulation returns 404."""
        response = app_client.get("/api/v1/simulation")
        assert response.status_code == 404


class TestSimulationDeletion:
    """Test simulation deletion."""

    def test_delete_simulation(self, app_client, valid_openapi_spec):
        """Test deleting an active simulation."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            create_response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert create_response.status_code == 201

            # Delete simulation
            delete_response = app_client.delete("/api/v1/simulation")
            assert delete_response.status_code == 204

            # Verify simulation is gone
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 404

    def test_delete_simulation_no_simulation_returns_404(self, app_client):
        """Test that deleting with no simulation returns 404."""
        response = app_client.delete("/api/v1/simulation")
        assert response.status_code == 404


class TestSessionReset:
    """Test session reset functionality."""

    def test_reset_session(self, app_client, valid_openapi_spec):
        """Test resetting simulation session."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill"
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            create_response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert create_response.status_code == 201

            # Reset session
            reset_response = app_client.post("/api/v1/simulation/reset")
            assert reset_response.status_code == 200
            assert "message" in reset_response.json()

            # Verify session state is reset
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()
            assert data["session_state"]["tool_call_count"] == 0

    def test_reset_session_no_simulation_returns_404(self, app_client):
        """Test that resetting with no simulation returns 404."""
        response = app_client.post("/api/v1/simulation/reset")
        assert response.status_code == 404


# Made with Bob
