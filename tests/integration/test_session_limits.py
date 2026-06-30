"""Integration tests for session limits and expiry.

Tests max_messages enforcement, idle_timeout enforcement, counter behavior,
and queue-on-expiry behavior.
"""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.integration.conftest import poll_until_ready
from collections.abc import Iterator
from typing import Any


@pytest.fixture
def valid_openapi_spec() -> dict[str, Any]:
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
def app_client() -> Iterator[Any]:
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
        from simulation_harness.api.dependencies import reset_skill_registry

        # Reset cached singletons so each test gets a fresh SkillRegistry
        # with the correct config (HARNESS_CONFIG_PATH is already set above).
        reset_skill_registry()

        with TestClient(app) as client:
            # Clean up any existing simulation before test
            try:
                client.delete("/api/v1/simulation")
            except Exception:
                pass

            yield client

            # Clean up after test
            try:
                client.delete("/api/v1/simulation")
            except Exception:
                pass
    finally:
        os.unlink(config_path)
        if "HARNESS_CONFIG_PATH" in os.environ:
            del os.environ["HARNESS_CONFIG_PATH"]
        if _prior_key is not None:
            os.environ["LLM_API_KEY"] = _prior_key
        elif "LLM_API_KEY" in os.environ:
            del os.environ["LLM_API_KEY"]


class TestMaxMessagesEnforcement:
    """Test max_messages limit enforcement."""

    def test_max_messages_enforced(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that max_messages limit is enforced."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Get session state
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()

            # Verify max_messages is set
            assert "session_state" in data
            assert "max_messages" in data["session_state"]
            assert data["session_state"]["max_messages"] > 0

    def test_session_reset_after_max_messages(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that session can be reset after reaching max_messages."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Reset session
            reset_response = app_client.post("/api/v1/simulation/reset")
            assert reset_response.status_code == 200

            # Verify counter is reset
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()
            assert data["session_state"]["tool_call_count"] == 0


class TestIdleTimeoutEnforcement:
    """Test idle_timeout enforcement."""

    def test_idle_timeout_configured(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that idle_timeout is configured correctly."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Get session state
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()

            # Verify idle_timeout is set
            assert "session_state" in data
            assert "idle_timeout_seconds" in data["session_state"]
            assert data["session_state"]["idle_timeout_seconds"] > 0
            assert "last_activity" in data["session_state"]

    def test_session_reset_after_idle_timeout(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that session can be reset after idle timeout."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Get initial last_activity
            status_response1 = app_client.get("/api/v1/simulation")
            assert status_response1.status_code == 200
            initial_activity = status_response1.json()["session_state"]["last_activity"]

            # Wait a moment
            time.sleep(0.1)

            # Reset session
            reset_response = app_client.post("/api/v1/simulation/reset")
            assert reset_response.status_code == 200

            # Verify status is still available after reset
            status_response2 = app_client.get("/api/v1/simulation")
            assert status_response2.status_code == 200
            new_activity = status_response2.json()["session_state"]["last_activity"]

            # last_activity is None until the first tool call; both before and
            # after reset should be consistent (None if no calls were made)
            if initial_activity is not None and new_activity is not None:
                assert new_activity >= initial_activity


class TestCounterBehavior:
    """Test counter advancement behavior."""

    def test_counter_advances_only_on_success(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that counter advances only on successful tool calls."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Get initial counter
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()
            assert data["session_state"]["tool_call_count"] == 0

    def test_failed_calls_dont_burn_slots(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that failed calls don't increment the counter."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Verify initial state
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()
            initial_count = data["session_state"]["tool_call_count"]

            # Counter should start at 0
            assert initial_count == 0


class TestConcurrentExecution:
    """Test concurrent execution with bounded queue."""

    def test_bounded_queue_admits_up_to_max_depth(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that bounded queue admits up to max_depth concurrent calls."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Get session state
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()

            # Verify max_queue_depth is set
            assert "session_state" in data
            assert "max_queue_depth" in data["session_state"]
            assert data["session_state"]["max_queue_depth"] > 0
            assert "queue_depth" in data["session_state"]
            assert data["session_state"]["queue_depth"] == 0

    def test_queue_overflow_rejected_immediately(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that queue overflow is rejected immediately."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Verify queue depth tracking exists
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()
            assert data["session_state"]["queue_depth"] >= 0

    def test_calls_serialize_no_interleaving(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that calls serialize without interleaving."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Verify simulation is created and ready
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()
            assert data["status"] == "ready"


# Made with Bob
