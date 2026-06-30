"""Unit tests for env-var config overrides."""

import pytest

from simulation_harness.config.env_overrides import apply_env_overrides
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


# Made with Bob
