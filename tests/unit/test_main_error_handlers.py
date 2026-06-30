"""Verify exception handlers wired in main.py map domain errors to status codes."""

import tempfile

import pytest
import yaml
from fastapi.testclient import TestClient
from typing import Any


def _valid_config() -> dict:
    return {
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


@pytest.fixture
def app_with_env(monkeypatch: pytest.MonkeyPatch) -> Any:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(_valid_config(), f)
        config_path = f.name
    monkeypatch.setenv("HARNESS_CONFIG_PATH", config_path)
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    import importlib
    import simulation_harness.main as m

    importlib.reload(m)

    from simulation_harness.utils.errors import (
        DatabaseValidationError,
        SimulationBusyError,
    )

    paths = {getattr(r, "path", None) for r in m.app.routes}
    if "/_boom_db_validation" not in paths:

        @m.app.get("/_boom_db_validation")
        async def _boom_db() -> dict:
            raise DatabaseValidationError(
                message="'name' is a required property", json_path="restaurants.0"
            )

    if "/_boom_busy" not in paths:

        @m.app.get("/_boom_busy")
        async def _boom_busy() -> dict:
            raise SimulationBusyError(queue_depth=2)

    return m.app


def test_database_validation_error_maps_to_422(app_with_env: Any) -> None:
    with TestClient(app_with_env) as client:
        resp = client.get("/_boom_db_validation")
    assert resp.status_code == 422
    body = resp.json()
    assert body["json_path"] == "restaurants.0"


def test_simulation_busy_error_maps_to_409(app_with_env: Any) -> None:
    with TestClient(app_with_env) as client:
        resp = client.get("/_boom_busy")
    assert resp.status_code == 409
    body = resp.json()
    assert body["queue_depth"] == 2
