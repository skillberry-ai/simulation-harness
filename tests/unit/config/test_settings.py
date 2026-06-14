"""Tests for non-secret configuration loading and validation."""

import pytest
import yaml

from simulation_harness.config import (
    HarnessConfig,
    TransportType,
    load_config,
    ConfigValidationError,
)


def _minimal_yaml_dict() -> dict:
    return {
        "llm": {
            "provider": "openai",
            "skill_generation_model": "gpt-4",
            "simulation_model": "gpt-4",
            "temperature": 0.0,
        },
        "skills": {"folder": "/tmp/skills"},
        "sessions": {
            "max_messages": 100,
            "idle_timeout_seconds": 3600,
            "max_concurrent_queue_depth": 8,
        },
        "mcp": {"transport": "sse"},
    }


class TestTransportType:
    def test_enum_values(self):
        assert TransportType.SSE.value == "sse"
        assert TransportType.STREAMABLE_HTTP.value == "streamable_http"


class TestServerSettings:
    def test_defaults(self):
        from simulation_harness.config.models import ServerSettings

        config = ServerSettings()
        assert config.host == "localhost"
        assert config.port == 8000

    def test_custom_values(self):
        from simulation_harness.config.models import ServerSettings

        config = ServerSettings(host="0.0.0.0", port=9000)
        assert config.host == "0.0.0.0"
        assert config.port == 9000

    def test_port_range_validated(self):
        from simulation_harness.config.models import ServerSettings

        with pytest.raises(ValueError):
            ServerSettings(port=0)
        with pytest.raises(ValueError):
            ServerSettings(port=70000)


class TestLLMConfig:
    def test_minimal_valid(self):
        from simulation_harness.config.models import LLMConfig

        config = LLMConfig(
            provider="openai",
            skill_generation_model="gpt-4",
            simulation_model="gpt-4",
            temperature=0.0,
        )
        assert config.provider == "openai"
        assert config.max_tokens is None

    def test_rejects_removed_fields(self):
        """LLMConfig must forbid removed fields like api_key_env."""
        from simulation_harness.config.models import LLMConfig

        with pytest.raises(ValueError):
            LLMConfig(
                provider="openai",
                skill_generation_model="gpt-4",
                simulation_model="gpt-4",
                api_key_env="OLD_FIELD",  # type: ignore[call-arg]
            )

    def test_temperature_range(self):
        from simulation_harness.config.models import LLMConfig

        with pytest.raises(ValueError):
            LLMConfig(
                provider="openai",
                skill_generation_model="gpt-4",
                simulation_model="gpt-4",
                temperature=3.0,
            )


class TestHarnessConfig:
    def test_construct_from_minimal_dict(self):
        config = HarnessConfig(**_minimal_yaml_dict())
        assert config.llm.provider == "openai"
        assert config.mcp.transport == TransportType.SSE
        assert config.server.host == "localhost"
        assert config.logging.level == "INFO"


class TestLoadConfig:
    def _write(self, tmp_path, data: dict) -> str:
        p = tmp_path / "harness.yaml"
        p.write_text(yaml.dump(data))
        return str(p)

    def test_loads_minimal_yaml(self, tmp_path):
        path = self._write(tmp_path, _minimal_yaml_dict())
        config = load_config(path)
        assert config.llm.provider == "openai"

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/harness.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("invalid: yaml: content: [")
        with pytest.raises(ConfigValidationError):
            load_config(str(p))

    def test_empty_file_raises(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        with pytest.raises(ConfigValidationError):
            load_config(str(p))

    def test_missing_required_section_raises(self, tmp_path):
        bad = _minimal_yaml_dict()
        del bad["llm"]
        path = self._write(tmp_path, bad)
        with pytest.raises(ConfigValidationError):
            load_config(path)

    def test_invalid_transport_raises(self, tmp_path):
        bad = _minimal_yaml_dict()
        bad["mcp"]["transport"] = "carrier_pigeon"
        path = self._write(tmp_path, bad)
        with pytest.raises(ConfigValidationError):
            load_config(path)

    def test_legacy_api_key_env_field_rejected(self, tmp_path):
        """Old api_key_env field must be rejected (extra='forbid')."""
        bad = _minimal_yaml_dict()
        bad["llm"]["api_key_env"] = "OPENAI_API_KEY"
        path = self._write(tmp_path, bad)
        with pytest.raises(ConfigValidationError):
            load_config(path)
