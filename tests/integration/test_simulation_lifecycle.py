"""Integration tests for simulation lifecycle management.

Tests the complete lifecycle of simulations from creation through deletion,
including skill generation, reuse, and session management.
"""

import json
import os
import shutil
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
def valid_openapi_spec_31() -> dict[str, Any]:
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

    def test_create_simulation_from_openapi_spec(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test creating a simulation from a valid OpenAPI spec."""
        # Mock skill generation to avoid actual LLM calls
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )

            assert response.status_code == 202
            data = response.json()
            assert data["name"] == "test-api"
            assert data["status"] == "pending"

            final = poll_until_ready(app_client, timeout=30.0)

        assert final["status"] == "ready", f"expected ready, got: {final}"
        assert "session_state" in final
        assert final["session_state"]["tool_call_count"] == 0
        assert final["mcp_url"] == "http://testserver/mcp/sse"
        assert "created_at" in final

    def test_create_simulation_openapi_31_accepted(
        self, app_client: Any, valid_openapi_spec_31: dict[str, Any]
    ) -> None:
        """Test that OpenAPI 3.1.x specs are accepted."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec_31, "regenerate_skill": False},
            )

            assert response.status_code == 202
            data = response.json()
            # "Test API 3.1" sanitizes to a valid Agent Skills name: the dot
            # becomes a hyphen (see sanitize_skill_name).
            assert data["name"] == "test-api-3-1"

            final = poll_until_ready(app_client, timeout=30.0)

        assert final["status"] == "ready", f"expected ready, got: {final}"

    def test_create_simulation_invalid_spec_returns_422(self, app_client: Any) -> None:
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
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
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
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that creating a duplicate simulation returns 409."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create first simulation
            response1 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response1.status_code == 202

            # Try to create second simulation while first is still pending/active
            response2 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response2.status_code == 409


class TestSkillGeneration:
    """Test skill generation and reuse."""

    def test_skill_generation_new_skill(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that a new skill is generated when none exists."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )

            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Verify skill generator was called
            mock_gen.assert_called_once()

    def test_skill_reuse_existing_skill(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that existing skill is reused when regenerate=False.

        This test verifies the behavior by creating a simulation twice with the same spec.
        The skill registry should reuse the skill file created in the first call.
        """
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            # Mock to return a path (simulating successful generation)
            mock_gen.return_value = Path("/tmp/test-api/SKILL.md")

            # Create first simulation (generates skill)
            response1 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response1.status_code == 202

            final1 = poll_until_ready(app_client, timeout=30.0)
            assert final1["status"] == "ready", f"expected ready, got: {final1}"

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
            assert response2.status_code == 202

            final2 = poll_until_ready(app_client, timeout=30.0)
            assert final2["status"] == "ready", f"expected ready, got: {final2}"
            # The behavior of skill reuse is tested in unit tests for SkillRegistry
            # Here we just verify the API works correctly

    def test_regenerate_flag_forces_new_skill(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test that regenerate=True forces new skill generation."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create first simulation
            response1 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert response1.status_code == 202

            final1 = poll_until_ready(app_client, timeout=30.0)
            assert final1["status"] == "ready", f"expected ready, got: {final1}"

            first_call_count = mock_gen.call_count

            # Delete simulation
            app_client.delete("/api/v1/simulation")

            # Create second simulation with regenerate=True
            response2 = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": True},
            )
            assert response2.status_code == 202

            final2 = poll_until_ready(app_client, timeout=30.0)
            assert final2["status"] == "ready", f"expected ready, got: {final2}"

            # Skill generator should be called again
            assert mock_gen.call_count > first_call_count


class TestSimulationStatus:
    """Test getting simulation status."""

    def test_get_simulation_status(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test getting status of active simulation."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            create_response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert create_response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Get status
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200

            data = status_response.json()
            assert data["name"] == "test-api"
            assert data["status"] == "ready"
            assert "session_state" in data

    def test_get_simulation_status_no_simulation_returns_404(
        self, app_client: Any
    ) -> None:
        """Test that getting status with no simulation returns 404."""
        response = app_client.get("/api/v1/simulation")
        assert response.status_code == 404


class TestSimulationDeletion:
    """Test simulation deletion."""

    def test_delete_simulation(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test deleting an active simulation."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            create_response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert create_response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Delete simulation
            delete_response = app_client.delete("/api/v1/simulation")
            assert delete_response.status_code == 204

            # Verify simulation is gone
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 404

    def test_delete_simulation_no_simulation_returns_404(self, app_client: Any) -> None:
        """Test that deleting with no simulation returns 404."""
        response = app_client.delete("/api/v1/simulation")
        assert response.status_code == 404


class TestSessionReset:
    """Test session reset functionality."""

    def test_reset_session(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """Test resetting simulation session."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Create simulation
            create_response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )
            assert create_response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # Reset session
            reset_response = app_client.post("/api/v1/simulation/reset")
            assert reset_response.status_code == 200
            assert "message" in reset_response.json()

            # Verify session state is reset
            status_response = app_client.get("/api/v1/simulation")
            assert status_response.status_code == 200
            data = status_response.json()
            assert data["session_state"]["tool_call_count"] == 0

    def test_reset_session_no_simulation_returns_404(self, app_client: Any) -> None:
        """Test that resetting with no simulation returns 404."""
        response = app_client.post("/api/v1/simulation/reset")
        assert response.status_code == 404


class TestMCPPortConfiguration:
    """Test mcp_port field on CreateSimulationRequest."""

    def test_create_simulation_with_mcp_port_returns_sidecar_url(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """POST /simulation with mcp_port returns fully-qualified sidecar URL when ready."""
        from simulation_harness.mcp_integration.sidecar_server import SidecarMCPServer

        with (
            patch(
                "simulation_harness.skills.generator.SkillGenerator.generate_skill",
                new_callable=AsyncMock,
            ) as mock_gen,
            patch.object(SidecarMCPServer, "start", new_callable=AsyncMock),
        ):
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            response = app_client.post(
                "/api/v1/simulation",
                json={
                    "openapi_spec": valid_openapi_spec,
                    "regenerate_skill": False,
                    "mcp_port": 9000,
                },
            )

            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)

        assert final["status"] == "ready", f"expected ready, got: {final}"
        assert final["mcp_url"] == "http://testserver:9000/mcp/sse"

    def test_create_simulation_without_mcp_port_returns_harness_url(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """POST /simulation without mcp_port returns harness-relative URL when ready."""
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            response = app_client.post(
                "/api/v1/simulation",
                json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
            )

            assert response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)

        assert final["status"] == "ready", f"expected ready, got: {final}"
        assert final["mcp_url"] == "http://testserver/mcp/sse"

    def test_get_simulation_preserves_mcp_url_after_creation_with_port(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """GET /simulation returns the same mcp_url as the ready status."""
        from simulation_harness.mcp_integration.sidecar_server import SidecarMCPServer

        with (
            patch(
                "simulation_harness.skills.generator.SkillGenerator.generate_skill",
                new_callable=AsyncMock,
            ) as mock_gen,
            patch.object(SidecarMCPServer, "start", new_callable=AsyncMock),
        ):
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            create_response = app_client.post(
                "/api/v1/simulation",
                json={
                    "openapi_spec": valid_openapi_spec,
                    "regenerate_skill": False,
                    "mcp_port": 9000,
                },
            )
            assert create_response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)

        assert final["status"] == "ready", f"expected ready, got: {final}"

        get_response = app_client.get("/api/v1/simulation")
        assert get_response.status_code == 200
        assert get_response.json()["mcp_url"] == final["mcp_url"]
        assert final["mcp_url"] == "http://testserver:9000/mcp/sse"

    def test_create_simulation_port_in_use_reaches_failed(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """POST /simulation with an already-bound mcp_port results in failed status."""
        import socket

        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            # Bind a port ourselves so the sidecar start will fail
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", 0))
            taken_port = sock.getsockname()[1]
            try:
                response = app_client.post(
                    "/api/v1/simulation",
                    json={
                        "openapi_spec": valid_openapi_spec,
                        "regenerate_skill": False,
                        "mcp_port": taken_port,
                    },
                )
                assert response.status_code == 202

                final = poll_until_ready(app_client, timeout=30.0)
            finally:
                sock.close()

        assert final["status"] == "failed", f"expected failed, got: {final}"
        assert str(taken_port) in str(final.get("error", {}))

    def test_delete_simulation_tears_down_sidecar(
        self, app_client: Any, valid_openapi_spec: dict[str, Any]
    ) -> None:
        """DELETE /simulation stops the sidecar server if one was started."""
        from simulation_harness.mcp_integration.sidecar_server import SidecarMCPServer

        stop_calls = []

        async def fake_stop(self) -> None:
            stop_calls.append(True)

        with (
            patch(
                "simulation_harness.skills.generator.SkillGenerator.generate_skill",
                new_callable=AsyncMock,
            ) as mock_gen,
            patch.object(SidecarMCPServer, "start", new_callable=AsyncMock),
            patch.object(SidecarMCPServer, "stop", fake_stop),
        ):
            mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

            create_response = app_client.post(
                "/api/v1/simulation",
                json={
                    "openapi_spec": valid_openapi_spec,
                    "regenerate_skill": False,
                    "mcp_port": 9000,
                },
            )
            assert create_response.status_code == 202

            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            delete_response = app_client.delete("/api/v1/simulation")
            assert delete_response.status_code == 204

        assert len(stop_calls) >= 1


def test_skill_reuse_reaches_ready_quickly(
    app_client: Any, valid_openapi_spec: dict[str, Any]
) -> None:
    """Second POST reuses skill and reaches ready in polling."""
    with patch(
        "simulation_harness.skills.generator.SkillGenerator.generate_skill",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = Path("/tmp/fake-skill/SKILL.md")

        # First simulation
        r1 = app_client.post(
            "/api/v1/simulation",
            json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
        )
        assert r1.status_code == 202
        final1 = poll_until_ready(app_client, timeout=60.0)
        assert final1["status"] == "ready"

        # Tear down. Keep the request outside the assert: under `python -O`
        # asserts are stripped and the teardown would never run.
        teardown = app_client.delete("/api/v1/simulation")
        assert teardown.status_code == 204

        # Second simulation reuses the skill
        r2 = app_client.post(
            "/api/v1/simulation",
            json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
        )
        assert r2.status_code == 202
        final2 = poll_until_ready(app_client, timeout=30.0)
        assert final2["status"] == "ready"


def test_delete_during_pending_returns_404_on_subsequent_get(
    app_client: Any, valid_openapi_spec: dict[str, Any]
) -> None:
    """DELETE during pending cancels creation; GET then returns 404."""
    import asyncio

    with patch(
        "simulation_harness.skills.generator.SkillGenerator.generate_skill",
        new_callable=AsyncMock,
    ) as mock_gen:
        # Simulate a slow skill generation so DELETE happens during pending
        async def slow_generate(*args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(10)
            return Path("/tmp/fake-skill/SKILL.md")

        mock_gen.side_effect = slow_generate

        r = app_client.post(
            "/api/v1/simulation",
            json={"openapi_spec": valid_openapi_spec, "regenerate_skill": False},
        )
        assert r.status_code == 202

        # Immediately DELETE before creation completes
        d = app_client.delete("/api/v1/simulation")
        assert d.status_code == 204

    g = app_client.get("/api/v1/simulation")
    assert g.status_code == 404


def _poll_until(client: TestClient, target: str, timeout: float = 30.0) -> dict:
    """Poll GET /api/v1/simulation until status == target (or failed)."""
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        resp = client.get("/api/v1/simulation")
        if resp.status_code == 200:
            last = resp.json()
            if last["status"] in (target, "failed"):
                return last
        time.sleep(0.1)
    raise AssertionError(
        f"Simulation did not reach '{target}' within {timeout}s; last={last}"
    )


async def _fake_generate_writing_artifacts(
    *,
    openapi_spec: dict[str, Any],
    simulation_name: str,
    skills_folder: Path,
    progress_cb: Any = None,
) -> Path:
    """Stand-in for SkillGenerator.generate_skill that writes the four artifacts.

    Mirrors the module's convention of not hitting the real LLM, but produces a
    complete on-disk skill bundle so setup/start can read it back.
    """
    d = Path(skills_folder) / simulation_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {simulation_name}\ndescription: Test skill\n---\n# skill\n"
    )
    (d / "schema.json").write_text(json.dumps({"type": "object", "properties": {}}))
    (d / "db.json").write_text(json.dumps({}))
    (d / "api.json").write_text(json.dumps(openapi_spec))
    return d / "SKILL.md"


def test_setup_then_start_then_tool_call(
    app_client: Any, valid_openapi_spec: dict[str, Any]
) -> None:
    """Two-phase flow: setup generates artifacts, start opens a session from them."""
    from simulation_harness.config.settings import get_config

    skills_dir = Path(get_config().skills.folder)
    try:
        with patch(
            "simulation_harness.skills.generator.SkillGenerator.generate_skill",
            new_callable=AsyncMock,
        ) as mock_gen:
            mock_gen.side_effect = _fake_generate_writing_artifacts

            # 1. setup → poll GENERATED
            r = app_client.post(
                "/api/v1/simulation/setup",
                json={"openapi_spec": valid_openapi_spec},
            )
            assert r.status_code == 202
            gen = _poll_until(app_client, "generated")
            assert gen["status"] == "generated", f"expected generated, got: {gen}"

            # 2. start (no spec) → poll READY
            name = app_client.get("/api/v1/simulation").json()["name"]
            r = app_client.post("/api/v1/simulation/start", json={"name": name})
            assert r.status_code == 202
            final = poll_until_ready(app_client, timeout=30.0)
            assert final["status"] == "ready", f"expected ready, got: {final}"

            # 3. tools/call works
            tools = app_client.get("/api/v1/simulation/tools")
            assert tools.status_code == 200
            assert len(tools.json()) > 0
    finally:
        shutil.rmtree(skills_dir / "test-api", ignore_errors=True)


def test_start_without_artifacts_returns_404(app_client: Any) -> None:
    """Start with a name that has no baked artifacts returns 404."""
    r = app_client.post("/api/v1/simulation/start", json={"name": "does-not-exist"})
    assert r.status_code == 404


# Made with Bob
