"""Unit tests for /healthz and /readyz probe endpoints."""

import os
import tempfile

import pytest
import yaml
from fastapi.testclient import TestClient


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
def client(monkeypatch):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(_valid_config(), f)
        config_path = f.name
    monkeypatch.setenv("HARNESS_CONFIG_PATH", config_path)
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    # Re-import main with fresh env
    import importlib
    import simulation_harness.main as m
    importlib.reload(m)
    with TestClient(m.app) as c:
        yield c, m


def test_healthz_returns_200(client):
    c, _ = client
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readyz_returns_200_when_not_draining(client):
    c, _ = client
    r = c.get("/readyz")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_readyz_returns_503_when_draining(client):
    c, m = client
    m.app.state.draining = True
    r = c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["status"] == "draining"


# Made with Bob
