"""End-to-end check: env vars override YAML at startup."""

import importlib
import os

import yaml
from pathlib import Path
from typing import Any
import pytest


def _base_yaml(tmpdir: Any) -> str:
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
        "server": {"host": "0.0.0.0", "port": 8086},
    }
    path = os.path.join(tmpdir, "harness.yaml")
    with open(path, "w") as f:
        yaml.dump(cfg, f)
    return path


def test_env_overrides_applied_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When HARNESS_SERVER_PORT is set, the imported config reflects it."""
    cfg_path = _base_yaml(str(tmp_path))
    monkeypatch.setenv("HARNESS_CONFIG_PATH", cfg_path)
    monkeypatch.setenv("HARNESS_SERVER_PORT", "9999")
    monkeypatch.setenv("HARNESS_SKILLS_FOLDER", str(tmp_path / "skills"))
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    import simulation_harness.main as m

    importlib.reload(m)

    assert m.config.server.port == 9999
    assert m.config.skills.folder == str(tmp_path / "skills")


def test_llm_model_env_overrides_applied_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Model names set only in the environment must reach the startup config.

    This is the path an orchestrator uses when it deploys the image without
    mounting a harness.yaml, so the YAML values below are the ones it cannot edit.
    """
    cfg_path = _base_yaml(str(tmp_path))
    monkeypatch.setenv("HARNESS_CONFIG_PATH", cfg_path)
    monkeypatch.setenv("HARNESS_SKILLS_FOLDER", str(tmp_path / "skills"))
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_LLM_SKILL_GENERATION_MODEL", "azure/gpt-4.1")
    monkeypatch.setenv("HARNESS_LLM_SIMULATION_MODEL", "openai/gpt-4o-mini")

    import simulation_harness.main as m

    importlib.reload(m)

    assert m.config.llm.skill_generation_model == "azure/gpt-4.1"
    assert m.config.llm.simulation_model == "openai/gpt-4o-mini"


# Made with Bob
