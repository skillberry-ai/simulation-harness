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


def _write_dotenv(directory: Path, body: str) -> Path:
    path = directory / ".env"
    path.write_text(body)
    return path


def test_dotenv_llm_model_reaches_startup_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Issue #13, end to end: models set only in `.env` must win over the YAML.

    Before the fix the request went out as the YAML model and the gateway
    answered 403, with nothing in the logs pointing at the dropped override.
    """
    cfg_path = _base_yaml(str(tmp_path))
    for name in (
        "HARNESS_LLM_SKILL_GENERATION_MODEL",
        "HARNESS_LLM_SIMULATION_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    _write_dotenv(
        tmp_path,
        f"LLM_API_KEY=test-key\n"
        f"HARNESS_CONFIG_PATH={cfg_path}\n"
        f"HARNESS_LLM_SKILL_GENERATION_MODEL=azure/gpt-5.4\n"
        f"HARNESS_LLM_SIMULATION_MODEL=azure/gpt-5.4\n",
    )
    monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_SKILLS_FOLDER", str(tmp_path / "skills"))
    monkeypatch.setenv("HARNESS_LOG_DESTINATION", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    import simulation_harness.main as m

    importlib.reload(m)

    assert m.config.llm.skill_generation_model == "azure/gpt-5.4"
    assert m.config.llm.simulation_model == "azure/gpt-5.4"


def test_dotenv_config_path_is_honored_without_process_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HARNESS_CONFIG_PATH from `.env` alone must select the YAML file."""
    cfg_path = _base_yaml(str(tmp_path))
    _write_dotenv(tmp_path, f"HARNESS_CONFIG_PATH={cfg_path}\n")
    monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_LOG_DESTINATION", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    import simulation_harness.main as m

    importlib.reload(m)

    assert m.config_path == cfg_path


def test_process_env_beats_dotenv_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A k8s `env:` block must not be shadowed by a `.env` left in the image."""
    cfg_path = _base_yaml(str(tmp_path))
    _write_dotenv(
        tmp_path,
        f"HARNESS_CONFIG_PATH={cfg_path}\nHARNESS_LLM_SIMULATION_MODEL=from-dotenv\n",
    )
    monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_LLM_SIMULATION_MODEL", "from-process-env")
    monkeypatch.setenv("HARNESS_LOG_DESTINATION", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    import simulation_harness.main as m

    importlib.reload(m)

    assert m.config.llm.simulation_model == "from-process-env"


def test_startup_logs_which_overrides_were_applied(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The line that ends the next investigation in seconds instead of an hour."""
    cfg_path = _base_yaml(str(tmp_path))
    _write_dotenv(
        tmp_path,
        f"HARNESS_CONFIG_PATH={cfg_path}\nHARNESS_LLM_SIMULATION_MODEL=azure/gpt-5.4\n",
    )
    monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
    monkeypatch.delenv("HARNESS_LLM_SIMULATION_MODEL", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_LOG_DESTINATION", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    import simulation_harness.main as m

    # configure_logging() replaces the root handlers, which detaches caplog, so
    # assert on the stream the harness actually writes to at startup.
    importlib.reload(m)

    logged = capsys.readouterr().err
    assert "env overrides applied" in logged, logged
    assert "HARNESS_LLM_SIMULATION_MODEL=azure/gpt-5.4 (.env)" in logged, logged


def test_startup_warns_about_misspelled_harness_key_in_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dropped override must be named, which is what #13 asked for as a fallback."""
    cfg_path = _base_yaml(str(tmp_path))
    _write_dotenv(
        tmp_path,
        f"HARNESS_CONFIG_PATH={cfg_path}\nHARNESS_LLM_MODEL=azure/gpt-5.4\n",
    )
    monkeypatch.delenv("HARNESS_CONFIG_PATH", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_LOG_DESTINATION", str(tmp_path / "logs"))
    monkeypatch.chdir(tmp_path)

    import simulation_harness.main as m

    importlib.reload(m)

    logged = capsys.readouterr().err
    assert "env overrides ignored" in logged, logged
    assert "HARNESS_LLM_MODEL" in logged, logged


# Made with Bob
