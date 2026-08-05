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
    (e.g. rossoctl, which passes only env vars) can still choose the models.
    """

    def test_provider_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HARNESS_LLM_PROVIDER", "azure")
        out = apply_env_overrides(_base())
        assert out.llm.provider == "azure"

    def test_skill_generation_model_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_LLM_SKILL_GENERATION_MODEL", "azure/gpt-5.4")
        out = apply_env_overrides(_base())
        assert out.llm.skill_generation_model == "azure/gpt-5.4"

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
        monkeypatch.setenv("HARNESS_LLM_SKILL_GENERATION_MODEL", "azure/gpt-5.4")
        monkeypatch.setenv("HARNESS_LLM_SIMULATION_MODEL", "openai/gpt-4o-mini")
        out = apply_env_overrides(_base())
        assert out.llm.skill_generation_model == "azure/gpt-5.4"
        assert out.llm.simulation_model == "openai/gpt-4o-mini"

    def test_skill_generation_max_tokens_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_LLM_SKILL_GENERATION_MAX_TOKENS", "40000")
        out = apply_env_overrides(_base())
        assert out.llm.skill_generation_max_tokens == 40000

    def test_skill_generation_max_tokens_invalid_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HARNESS_LLM_SKILL_GENERATION_MAX_TOKENS", "lots")
        with pytest.raises(ValueError, match="HARNESS_LLM_SKILL_GENERATION_MAX_TOKENS"):
            apply_env_overrides(_base())

    def test_unset_llm_env_vars_leave_yaml_values_intact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in (
            "HARNESS_LLM_PROVIDER",
            "HARNESS_LLM_SKILL_GENERATION_MODEL",
            "HARNESS_LLM_SIMULATION_MODEL",
            "HARNESS_LLM_SKILL_GENERATION_MAX_TOKENS",
        ):
            monkeypatch.delenv(name, raising=False)
        c = _base()
        out = apply_env_overrides(c)
        assert out.llm.provider == c.llm.provider
        assert out.llm.skill_generation_model == c.llm.skill_generation_model
        assert out.llm.simulation_model == c.llm.simulation_model
        assert out.llm.skill_generation_max_tokens == c.llm.skill_generation_max_tokens

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


# Made with Bob
