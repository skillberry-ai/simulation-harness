"""Unit tests for env-var config overrides."""

from pathlib import Path

import pytest

from simulation_harness.config.env_overrides import (
    applied_overrides,
    apply_env_overrides,
    unrecognized_dotenv_keys,
)
from simulation_harness.config.models import HarnessConfig


def _base() -> HarnessConfig:
    return HarnessConfig(
        llm={
            "provider": "openai",
            "skill_generation_model": "gpt-4",
            "simulation_model": "gpt-4",
            "temperature": 0,
        },
        skills={"folder": "./skills-store"},
        sessions={
            "max_messages": 100,
            "idle_timeout_seconds": 3600,
            "max_concurrent_queue_depth": 8,
        },
        mcp={"transport": "sse"},
    )


class TestApplyEnvOverrides:
    def test_no_env_vars_returns_unchanged_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HARNESS_SERVER_HOST", raising=False)
        monkeypatch.delenv("HARNESS_SERVER_PORT", raising=False)
        c = _base()
        out = apply_env_overrides(c)
        assert out.server.host == c.server.host
        assert out.server.port == c.server.port

    def test_server_port_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_SERVER_PORT", "9090")
        out = apply_env_overrides(_base())
        assert out.server.port == 9090

    def test_server_host_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_SERVER_HOST", "127.0.0.1")
        out = apply_env_overrides(_base())
        assert out.server.host == "127.0.0.1"

    def test_skills_folder_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_SKILLS_FOLDER", "/data/skills")
        out = apply_env_overrides(_base())
        assert out.skills.folder == "/data/skills"

    def test_logging_level_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_LOG_LEVEL", "DEBUG")
        out = apply_env_overrides(_base())
        assert out.logging.level == "DEBUG"

    def test_logging_destination_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_LOG_DESTINATION", "/var/log/harness")
        out = apply_env_overrides(_base())
        assert out.logging.destination_folder == "/var/log/harness"

    def test_mcp_transport_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_MCP_TRANSPORT", "streamable_http")
        out = apply_env_overrides(_base())
        assert out.mcp.transport.value == "streamable_http"

    def test_sessions_max_messages_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_SESSIONS_MAX_MESSAGES", "250")
        out = apply_env_overrides(_base())
        assert out.sessions.max_messages == 250

    def test_sessions_idle_timeout_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_SESSIONS_IDLE_TIMEOUT_SECONDS", "60")
        out = apply_env_overrides(_base())
        assert out.sessions.idle_timeout_seconds == 60

    def test_invalid_int_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_SERVER_PORT", "not-a-number")
        with pytest.raises(ValueError, match="HARNESS_SERVER_PORT"):
            apply_env_overrides(_base())

    def test_invalid_log_level_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_LOG_LEVEL", "VERBOSE")
        with pytest.raises(ValueError):
            apply_env_overrides(_base())

    def test_overrides_update_global_config_singleton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_config() must return the overridden config, not the pre-override one.

        Otherwise the skill registry, dependency injection, and any other consumer
        of get_config() will silently ignore HARNESS_* env vars.
        """
        from simulation_harness.config.settings import get_config

        monkeypatch.setenv("HARNESS_SKILLS_FOLDER", "/data/skills-store-override")
        apply_env_overrides(_base())
        assert get_config().skills.folder == "/data/skills-store-override"

    def test_autostart_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_AUTOSTART_SIMULATION", "acme")
        out = apply_env_overrides(_base())
        assert out.startup.autostart_simulation == "acme"

    def test_autostart_enabled_true_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_AUTOSTART_ENABLED", "true")
        out = apply_env_overrides(_base())
        assert out.startup.autostart_enabled is True

    def test_autostart_enabled_false_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_AUTOSTART_ENABLED", "false")
        out = apply_env_overrides(_base())
        assert out.startup.autostart_enabled is False

    def test_autostart_enabled_invalid_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_AUTOSTART_ENABLED", "notabool")
        with pytest.raises(ValueError):
            apply_env_overrides(_base())


class TestLLMOverrides:
    """The llm: block is overridable so an orchestrator that mounts no ConfigMap
    (passing only env vars) can still choose the models.
    """

    def test_provider_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_LLM_PROVIDER", "azure")
        out = apply_env_overrides(_base())
        assert out.llm.provider == "azure"

    def test_skill_generation_model_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_LLM_SKILL_GENERATION_MODEL", "azure/gpt-4.1")
        out = apply_env_overrides(_base())
        assert out.llm.skill_generation_model == "azure/gpt-4.1"

    def test_simulation_model_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_LLM_SIMULATION_MODEL", "openai/gpt-4o-mini")
        out = apply_env_overrides(_base())
        assert out.llm.simulation_model == "openai/gpt-4o-mini"

    def test_generation_and_simulation_models_are_independent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A big model for generation and a cheap one for the hot path is the
        main use case, so overriding one must not disturb the other.
        """
        monkeypatch.setenv("HARNESS_LLM_SKILL_GENERATION_MODEL", "azure/gpt-4.1")
        monkeypatch.setenv("HARNESS_LLM_SIMULATION_MODEL", "openai/gpt-4o-mini")
        out = apply_env_overrides(_base())
        assert out.llm.skill_generation_model == "azure/gpt-4.1"
        assert out.llm.simulation_model == "openai/gpt-4o-mini"

    def test_unset_llm_env_vars_leave_yaml_values_intact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in (
            "HARNESS_LLM_PROVIDER",
            "HARNESS_LLM_SKILL_GENERATION_MODEL",
            "HARNESS_LLM_SIMULATION_MODEL",
        ):
            monkeypatch.delenv(name, raising=False)
        c = _base()
        out = apply_env_overrides(c)
        assert out.llm.provider == c.llm.provider
        assert out.llm.skill_generation_model == c.llm.skill_generation_model
        assert out.llm.simulation_model == c.llm.simulation_model

    def test_llm_overrides_update_global_config_singleton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The agent and the generation pipeline read models via get_config(),
        so the singleton must carry the override too.
        """
        from simulation_harness.config.settings import get_config

        monkeypatch.setenv("HARNESS_LLM_SIMULATION_MODEL", "openai/gpt-4o-mini")
        apply_env_overrides(_base())
        assert get_config().llm.simulation_model == "openai/gpt-4o-mini"


class TestDotenvIngress:
    """Issue #13: HARNESS_* keys in `.env` were silently discarded, so the YAML
    model won and the first LLM call 403'd with no hint that the override had
    been dropped. `.env.example` documents these keys, so `.env` is a supported
    channel, not a secrets-only file.
    """

    def _write_env(self, directory: Path, body: str) -> str:
        path = directory / ".env"
        path.write_text(body)
        return str(path)

    def test_model_override_from_dotenv_only(self, tmp_path: Path) -> None:
        env_file = self._write_env(
            tmp_path, "HARNESS_LLM_SKILL_GENERATION_MODEL=azure/gpt-5.4\n"
        )
        out = apply_env_overrides(_base(), env_file=env_file)
        assert out.llm.skill_generation_model == "azure/gpt-5.4"

    def test_both_models_from_dotenv_only(self, tmp_path: Path) -> None:
        """The exact reproduction from the issue."""
        env_file = self._write_env(
            tmp_path,
            "LLM_API_KEY=sk-not-a-real-key\n"
            "HARNESS_LLM_SKILL_GENERATION_MODEL=azure/gpt-5.4\n"
            "HARNESS_LLM_SIMULATION_MODEL=azure/gpt-5.4\n",
        )
        out = apply_env_overrides(_base(), env_file=env_file)
        assert out.llm.skill_generation_model == "azure/gpt-5.4"
        assert out.llm.simulation_model == "azure/gpt-5.4"

    def test_process_env_beats_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """k8s injects an `env:` block; it must not be shadowed by a stray file."""
        env_file = self._write_env(
            tmp_path,
            "HARNESS_LLM_SIMULATION_MODEL=from-dotenv\n",  # pragma: allowlist secret
        )
        monkeypatch.setenv("HARNESS_LLM_SIMULATION_MODEL", "from-process-env")
        out = apply_env_overrides(_base(), env_file=env_file)
        assert out.llm.simulation_model == "from-process-env"

    def test_non_llm_keys_also_come_from_dotenv(self, tmp_path: Path) -> None:
        env_file = self._write_env(
            tmp_path,
            "HARNESS_SERVER_PORT=9091\nHARNESS_MCP_TRANSPORT=streamable_http\n",  # pragma: allowlist secret
        )
        out = apply_env_overrides(_base(), env_file=env_file)
        assert out.server.port == 9091
        assert out.mcp.transport.value == "streamable_http"

    def test_bad_int_in_dotenv_raises(self, tmp_path: Path) -> None:
        """A typo in `.env` must fail as loudly as one in the process env."""
        env_file = self._write_env(tmp_path, "HARNESS_SERVER_PORT=eight-thousand\n")
        with pytest.raises(ValueError, match="HARNESS_SERVER_PORT"):
            apply_env_overrides(_base(), env_file=env_file)

    def test_bad_bool_in_dotenv_raises(self, tmp_path: Path) -> None:
        env_file = self._write_env(tmp_path, "HARNESS_AUTOSTART_ENABLED=maybe\n")
        with pytest.raises(ValueError, match="HARNESS_AUTOSTART_ENABLED"):
            apply_env_overrides(_base(), env_file=env_file)

    def test_env_file_none_ignores_dotenv(self, tmp_path: Path) -> None:
        env_file = self._write_env(tmp_path, "HARNESS_LLM_SIMULATION_MODEL=ignored\n")
        assert Path(env_file).exists()
        out = apply_env_overrides(_base(), env_file=None)
        assert out.llm.simulation_model == "gpt-4"

    def test_dotenv_is_read_from_cwd_by_default(self, tmp_path: Path) -> None:
        """The default is a bare `.env`, resolved against the working directory —
        the same file `.env.example` is copied to.
        """
        self._write_env(
            tmp_path,
            "HARNESS_LLM_SIMULATION_MODEL=from-cwd-dotenv\n",  # pragma: allowlist secret
        )
        import os

        os.chdir(tmp_path)
        out = apply_env_overrides(_base())
        assert out.llm.simulation_model == "from-cwd-dotenv"


class TestAppliedOverrideReporting:
    """`apply_env_overrides` runs before logging is configured (main.py applies
    overrides at import, configures logging from the result), so it records what
    it did and main.py logs the record afterwards. Without this line, a dropped
    or misspelled override is invisible — the cost that made issue #13 expensive.
    """

    def _write_env(self, directory: Path, body: str) -> str:
        path = directory / ".env"
        path.write_text(body)
        return str(path)

    def test_reports_dotenv_source(self, tmp_path: Path) -> None:
        env_file = self._write_env(
            tmp_path, "HARNESS_LLM_SIMULATION_MODEL=azure/gpt-5.4\n"
        )
        apply_env_overrides(_base(), env_file=env_file)
        assert applied_overrides() == {
            "HARNESS_LLM_SIMULATION_MODEL": ("azure/gpt-5.4", env_file)
        }

    def test_reports_process_env_source(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_SERVER_PORT", "9090")
        apply_env_overrides(_base(), env_file=None)
        assert applied_overrides() == {"HARNESS_SERVER_PORT": ("9090", "process env")}

    def test_report_is_empty_when_nothing_overridden(self) -> None:
        apply_env_overrides(_base(), env_file=None)
        assert applied_overrides() == {}

    def test_report_is_replaced_not_accumulated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_SERVER_PORT", "9090")
        apply_env_overrides(_base(), env_file=None)
        monkeypatch.delenv("HARNESS_SERVER_PORT")
        apply_env_overrides(_base(), env_file=None)
        assert applied_overrides() == {}

    def test_unrecognized_harness_key_in_dotenv_is_reported(
        self, tmp_path: Path
    ) -> None:
        """A typo such as HARNESS_LLM_MODEL should be named, not silently dropped."""
        env_file = self._write_env(
            tmp_path, "HARNESS_LLM_MODEL=azure/gpt-5.4\nHARNESS_TYPO=1\n"
        )
        apply_env_overrides(_base(), env_file=env_file)
        assert unrecognized_dotenv_keys() == ["HARNESS_LLM_MODEL", "HARNESS_TYPO"]

    def test_recognized_and_secret_keys_are_not_flagged(self, tmp_path: Path) -> None:
        """`.env` legitimately holds secrets and HARNESS_CONFIG_PATH alongside
        the overrides; none of those are typos.
        """
        env_file = self._write_env(
            tmp_path,
            "LLM_API_KEY=sk-not-a-real-key\n"
            "LLM_API_BASE=https://gateway.example.com/v1\n"
            "HARNESS_CONFIG_PATH=config/harness.yaml\n"
            "HARNESS_LLM_NO_CACHE=1\n"
            "HARNESS_SERVER_PORT=9090\n",
        )
        apply_env_overrides(_base(), env_file=env_file)
        assert unrecognized_dotenv_keys() == []


# Made with Bob
