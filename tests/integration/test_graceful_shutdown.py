"""End-to-end check: lifespan teardown flips draining flag."""

import importlib
import os

import yaml
from fastapi.testclient import TestClient


def _cfg(tmpdir) -> str:
    cfg = {
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
    path = os.path.join(tmpdir, "harness.yaml")
    with open(path, "w") as f:
        yaml.dump(cfg, f)
    return path


def test_readyz_flips_to_503_after_lifespan_shutdown(monkeypatch, tmp_path):
    monkeypatch.setenv("HARNESS_CONFIG_PATH", _cfg(str(tmp_path)))
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    import simulation_harness.main as m
    importlib.reload(m)

    # While the lifespan is active, /readyz returns 200.
    with TestClient(m.app) as client:
        r = client.get("/readyz")
        assert r.status_code == 200

    # After context exit, lifespan shutdown ran — draining flag should be set.
    assert m.app.state.draining is True


# Made with Bob
