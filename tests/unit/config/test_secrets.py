"""Tests for the Secrets pydantic-settings class."""

import json

import pytest
from pydantic import ValidationError

from simulation_harness.config.secrets import Secrets


class TestSecretsLoading:
    def test_loads_required_field_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
        monkeypatch.delenv("LLM_API_BASE", raising=False)

        secrets = Secrets(_env_file=None)

        assert secrets.llm_api_key.get_secret_value() == "sk-test-123"
        assert secrets.llm_api_base is None

    def test_loads_optional_api_base_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-123")
        monkeypatch.setenv("LLM_API_BASE", "https://example.invalid/v1")

        secrets = Secrets(_env_file=None)

        assert secrets.llm_api_base == "https://example.invalid/v1"

    def test_missing_required_raises_validation_error(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        with pytest.raises(ValidationError):
            Secrets(_env_file=None)

    def test_empty_string_required_raises_validation_error(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "")

        with pytest.raises(ValidationError):
            Secrets(_env_file=None)

    def test_empty_string_api_base_raises_validation_error(self, monkeypatch):
        """llm_api_base='' must be rejected — empty string is not a valid URL."""
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_API_BASE", "")

        with pytest.raises(ValidationError):
            Secrets(_env_file=None)

    def test_case_insensitive_env_lookup(self, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.setenv("llm_api_key", "sk-lower")

        secrets = Secrets(_env_file=None)

        assert secrets.llm_api_key.get_secret_value() == "sk-lower"


class TestSecretsRedaction:
    def test_repr_redacts_secret_value(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-leak-me")

        secrets = Secrets(_env_file=None)

        assert "sk-leak-me" not in repr(secrets)
        assert "sk-leak-me" not in str(secrets)

    def test_model_dump_json_redacts_secret_value(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-leak-me")

        secrets = Secrets(_env_file=None)
        dumped = secrets.model_dump_json()

        assert "sk-leak-me" not in dumped
        parsed = json.loads(dumped)
        assert "llm_api_key" in parsed


class TestLoadSecretsHelper:
    def test_load_secrets_returns_secrets_instance(self, monkeypatch, tmp_path):
        from simulation_harness.config import load_secrets

        monkeypatch.chdir(tmp_path)  # avoid picking up project .env
        monkeypatch.setenv("LLM_API_KEY", "sk-via-helper")
        monkeypatch.delenv("LLM_API_BASE", raising=False)

        secrets = load_secrets(env_file=None)

        assert isinstance(secrets, Secrets)
        assert secrets.llm_api_key.get_secret_value() == "sk-via-helper"

    def test_load_secrets_re_raises_validation_error(self, monkeypatch, tmp_path):
        from pydantic import ValidationError

        from simulation_harness.config import load_secrets

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        with pytest.raises(ValidationError):
            load_secrets(env_file=None)


class TestGetSecretsAccessor:
    def test_get_secrets_raises_before_load(self, monkeypatch):
        # Reset the module-level global to simulate fresh state.
        from simulation_harness.config import settings as settings_mod

        monkeypatch.setattr(settings_mod, "_global_secrets", None)

        with pytest.raises(RuntimeError, match="Secrets not loaded"):
            settings_mod.get_secrets()

    def test_get_secrets_returns_loaded_instance(self, monkeypatch, tmp_path):
        from simulation_harness.config import get_secrets, load_secrets

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LLM_API_KEY", "sk-loaded")

        loaded = load_secrets(env_file=None)

        assert get_secrets() is loaded


class TestStartupContract:
    """The split startup contract: load_config succeeds without key; load_secrets fails."""

    def test_load_config_succeeds_without_llm_api_key(self, tmp_path, monkeypatch):
        """load_config() must not raise even when LLM_API_KEY is absent."""
        import yaml
        from simulation_harness.config import load_config

        monkeypatch.delenv("LLM_API_KEY", raising=False)
        config_file = tmp_path / "harness.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "llm": {
                        "provider": "openai",
                        "skill_generation_model": "gpt-4",
                        "simulation_model": "gpt-4",
                        "temperature": 0.0,
                    },
                    "skills": {"folder": str(tmp_path / "skills")},
                    "sessions": {
                        "max_messages": 10,
                        "idle_timeout_seconds": 60,
                        "max_concurrent_queue_depth": 4,
                    },
                    "mcp": {"transport": "sse"},
                }
            )
        )

        config = load_config(str(config_file))
        assert config.llm.provider == "openai"

    def test_load_secrets_fails_without_llm_api_key(self, tmp_path, monkeypatch):
        """load_secrets() must raise pydantic.ValidationError when LLM_API_KEY is absent."""
        from pydantic import ValidationError
        from simulation_harness.config import load_secrets

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LLM_API_KEY", raising=False)

        with pytest.raises(ValidationError):
            load_secrets(env_file=None)
