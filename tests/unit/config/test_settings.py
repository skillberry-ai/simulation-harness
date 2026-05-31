"""Tests for configuration loading and validation."""

import os

import pytest
import yaml

from simulation_harness.config import (
    HarnessConfig,
    ServerConfig,
    TransportType,
    load_config,
    ConfigValidationError,
)


class TestConfigModels:
    """Test Pydantic config models."""

    def test_transport_type_enum_values(self):
        """Test TransportType enum has correct values."""
        assert TransportType.SSE.value == "sse"
        assert TransportType.STREAMABLE_HTTP.value == "streamable_http"

    def test_server_config_with_api_key(self):
        """Test ServerConfig with literal api_key."""
        config = ServerConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-everything"],
            api_key="test-key-123",
            transport="sse",
        )
        assert config.api_key == "test-key-123"
        assert config.api_key_env is None
        assert config.transport == TransportType.SSE

    def test_server_config_with_api_key_env(self):
        """Test ServerConfig with api_key_env."""
        config = ServerConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-everything"],
            api_key_env="MY_API_KEY",
            transport="streamable_http",
        )
        assert config.api_key is None
        assert config.api_key_env == "MY_API_KEY"
        assert config.transport == TransportType.STREAMABLE_HTTP

    def test_server_config_requires_api_key_or_env(self):
        """Test ServerConfig requires either api_key or api_key_env."""
        with pytest.raises(ValueError, match="Either api_key or api_key_env must be provided"):
            ServerConfig(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-everything"],
                transport="sse",
            )

    def test_server_config_rejects_both_api_keys(self):
        """Test ServerConfig rejects both api_key and api_key_env."""
        with pytest.raises(ValueError, match="Cannot provide both api_key and api_key_env"):
            ServerConfig(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-everything"],
                api_key="test-key",
                api_key_env="MY_KEY",
                transport="sse",
            )

    def test_server_config_invalid_transport(self):
        """Test ServerConfig rejects invalid transport."""
        with pytest.raises(ValueError):
            ServerConfig(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-everything"],
                api_key="test-key",
                transport="invalid_transport",
            )

    def test_server_settings_with_defaults(self):
        """Test ServerSettings with default host and port."""
        from simulation_harness.config.models import ServerSettings
        
        config = ServerSettings()
        assert config.host == "localhost"
        assert config.port == 8000

    def test_server_settings_with_custom_values(self):
        """Test ServerSettings with custom host and port."""
        from simulation_harness.config.models import ServerSettings
        
        config = ServerSettings(host="0.0.0.0", port=9000)
        assert config.host == "0.0.0.0"
        assert config.port == 9000

    def test_server_settings_validates_port_range(self):
        """Test ServerSettings validates port is in valid range."""
        from simulation_harness.config.models import ServerSettings
        
        with pytest.raises(ValueError):
            ServerSettings(port=0)
        
        with pytest.raises(ValueError):
            ServerSettings(port=65536)
        
        # Valid ports should work
        config = ServerSettings(port=1)
        assert config.port == 1
        
        config = ServerSettings(port=65535)
        assert config.port == 65535

    def test_harness_config_structure(self):
        """Test HarnessConfig with the new configuration sections."""
        config = HarnessConfig(
            llm={
                "provider": "openai",
                "api_key": "test-key",
                "skill_generation_model": "gpt-4",
                "simulation_model": "gpt-4",
                "temperature": 0,
            },
            skills={"folder": "./skills"},
            sessions={
                "max_messages": 100,
                "idle_timeout_seconds": 3600,
                "max_concurrent_queue_depth": 8,
            },
            mcp={"transport": "sse"},
            server={"host": "localhost", "port": 8000},
        )
        assert config.llm.provider == "openai"
        assert config.llm.api_key == "test-key"
        assert config.skills.folder == "./skills"
        assert config.sessions.max_messages == 100
        assert config.server.host == "localhost"
        assert config.server.port == 8000
        assert config.sessions.idle_timeout_seconds == 3600
        assert config.sessions.max_concurrent_queue_depth == 8
        assert config.mcp.transport == TransportType.SSE

    def test_llm_config_structure(self):
        """Test LLM configuration section."""
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key_env": "OPENAI_API_KEY",
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
        config = HarnessConfig(**config_data)
        assert config.llm.provider == "openai"
        assert config.llm.skill_generation_model == "gpt-4"
        assert config.llm.simulation_model == "gpt-4"
        assert config.llm.temperature == 0
    def test_llm_config_requires_api_key_or_env(self):
        """Test LLMConfig requires either api_key or api_key_env."""
        config_data = {
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
            },
            "mcp": {"transport": "sse"},
        }
        with pytest.raises(ValueError, match="Either api_key or api_key_env must be provided"):
            HarnessConfig(**config_data)

    def test_llm_config_with_api_key(self):
        """Test LLMConfig with literal api_key."""
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key-123",
                "skill_generation_model": "gpt-4",
                "simulation_model": "gpt-4",
                "temperature": 0,
            },
            "skills": {"folder": "./skills"},
            "sessions": {
                "max_messages": 100,
                "idle_timeout_seconds": 3600,
            },
            "mcp": {"transport": "sse"},
        }
        config = HarnessConfig(**config_data)
        assert config.llm.api_key == "test-key-123"
        assert config.llm.api_key_env is None

    def test_llm_config_with_both_api_keys(self):
        """Test LLMConfig allows both api_key and api_key_env (fallback pattern)."""
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key-123",
                "api_key_env": "OPENAI_API_KEY",
                "skill_generation_model": "gpt-4",
                "simulation_model": "gpt-4",
                "temperature": 0,
            },
            "skills": {"folder": "./skills"},
            "sessions": {
                "max_messages": 100,
                "idle_timeout_seconds": 3600,
            },
            "mcp": {"transport": "sse"},
        }
        config = HarnessConfig(**config_data)
        assert config.llm.api_key == "test-key-123"
        assert config.llm.api_key_env == "OPENAI_API_KEY"

    def test_llm_config_with_api_base_literal(self):
        """Test LLMConfig accepts literal api_base."""
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key-123",
                "api_base": "https://example.test/v1",
                "skill_generation_model": "gpt-4",
                "simulation_model": "gpt-4",
                "temperature": 0,
            },
            "skills": {"folder": "./skills"},
            "sessions": {
                "max_messages": 100,
                "idle_timeout_seconds": 3600,
            },
            "mcp": {"transport": "sse"},
        }
        config = HarnessConfig(**config_data)
        assert config.llm.api_base == "https://example.test/v1"
        assert config.llm.api_base_env is None

    def test_llm_config_with_api_base_env(self):
        """Test LLMConfig accepts api_base_env."""
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key-123",
                "api_base_env": "OPENAI_API_BASE",
                "skill_generation_model": "gpt-4",
                "simulation_model": "gpt-4",
                "temperature": 0,
            },
            "skills": {"folder": "./skills"},
            "sessions": {
                "max_messages": 100,
                "idle_timeout_seconds": 3600,
            },
            "mcp": {"transport": "sse"},
        }
        config = HarnessConfig(**config_data)
        assert config.llm.api_base is None
        assert config.llm.api_base_env == "OPENAI_API_BASE"


    def test_logging_config_with_defaults(self):
        """Test LoggingConfig with default values."""
        from simulation_harness.config.models import LoggingConfig
        
        config = LoggingConfig()
        assert config.level == "INFO"
        assert config.destination_folder == "./logs"

    def test_logging_config_with_custom_values(self):
        """Test LoggingConfig with custom level and destination."""
        from simulation_harness.config.models import LoggingConfig
        
        config = LoggingConfig(level="DEBUG", destination_folder="/var/log/harness")
        assert config.level == "DEBUG"
        assert config.destination_folder == "/var/log/harness"

    def test_logging_config_validates_level(self):
        """Test LoggingConfig validates log level is valid."""
        from simulation_harness.config.models import LoggingConfig
        
        # Valid levels should work
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = LoggingConfig(level=level)
            assert config.level == level
        
        # Invalid level should raise ValueError
        with pytest.raises(ValueError, match="Invalid log level"):
            LoggingConfig(level="INVALID")
        
        with pytest.raises(ValueError, match="Invalid log level"):
            LoggingConfig(level="debug")  # lowercase should fail

    def test_harness_config_with_logging_defaults(self):
        """Test HarnessConfig includes logging with defaults."""
        config = HarnessConfig(
            llm={
                "provider": "openai",
                "api_key": "test-key",
                "skill_generation_model": "gpt-4",
                "simulation_model": "gpt-4",
                "temperature": 0,
            },
            skills={"folder": "./skills"},
            sessions={
                "max_messages": 100,
                "idle_timeout_seconds": 3600,
                "max_concurrent_queue_depth": 8,
            },
            mcp={"transport": "sse"},
        )
        # Should have default logging config
        assert config.logging.level == "INFO"
        assert config.logging.destination_folder == "./logs"

    def test_harness_config_with_custom_logging(self):
        """Test HarnessConfig with custom logging configuration."""
        config = HarnessConfig(
            llm={
                "provider": "openai",
                "api_key": "test-key",
                "skill_generation_model": "gpt-4",
                "simulation_model": "gpt-4",
                "temperature": 0,
            },
            skills={"folder": "./skills"},
            sessions={
                "max_messages": 100,
                "idle_timeout_seconds": 3600,
                "max_concurrent_queue_depth": 8,
            },
            mcp={"transport": "sse"},
            logging={"level": "DEBUG", "destination_folder": "/custom/logs"},
        )
        assert config.logging.level == "DEBUG"
        assert config.logging.destination_folder == "/custom/logs"


class TestConfigLoader:
    """Test configuration loading from YAML."""

    def test_load_config_from_valid_yaml(self, tmp_path):
        """Test loading valid configuration from YAML file."""
        config_file = tmp_path / "harness.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key-123",
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
        config_file.write_text(yaml.dump(config_data))

        config = load_config(str(config_file))

        assert isinstance(config, HarnessConfig)
        assert config.llm.provider == "openai"
        assert config.llm.api_key == "test-key-123"
        assert config.skills.folder == "./skills"
        assert config.sessions.max_messages == 100
        assert config.mcp.transport == TransportType.SSE

    def test_load_config_with_api_key_env(self, tmp_path):
        """Test loading config with api_key_env in the new llm section."""
        config_file = tmp_path / "harness.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key_env": "TEST_API_KEY",
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
            "mcp": {"transport": "streamable_http"},
        }
        config_file.write_text(yaml.dump(config_data))

        # Set environment variable
        os.environ["TEST_API_KEY"] = "env-resolved-key"
        try:
            config = load_config(str(config_file))
            assert config.llm.api_key_env == "TEST_API_KEY"
            assert config.mcp.transport == TransportType.STREAMABLE_HTTP
        finally:
            del os.environ["TEST_API_KEY"]

    def test_load_config_with_api_base_env(self, tmp_path):
        """Test loading config with api_base_env resolved from environment."""
        config_file = tmp_path / "api_base_env.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key-123",
                "api_base_env": "TEST_API_BASE",
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
        config_file.write_text(yaml.dump(config_data))

        os.environ["TEST_API_BASE"] = "https://example.test/v1"
        try:
            config = load_config(str(config_file))
            assert config.llm.api_base_env == "TEST_API_BASE"
        finally:
            del os.environ["TEST_API_BASE"]

    def test_load_config_missing_api_key_env_var(self, tmp_path):
        """Test loading config fails when api_key_env does not resolve."""
        config_file = tmp_path / "missing_api_key_env.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key_env": "MISSING_API_KEY",
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
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ConfigValidationError, match="api_key_env"):
            load_config(str(config_file))

    def test_load_config_missing_api_base_env_var(self, tmp_path):
        """Test loading config fails when api_base_env does not resolve."""
        config_file = tmp_path / "missing_api_base_env.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key-123",
                "api_base_env": "MISSING_API_BASE",
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
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ConfigValidationError, match="api_base_env"):
            load_config(str(config_file))

    def test_load_config_missing_file(self):
        """Test loading config from non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/harness.yaml")

    def test_load_config_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML raises ConfigValidationError."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: content: [")

        with pytest.raises(ConfigValidationError, match="Failed to parse YAML"):
            load_config(str(config_file))

    def test_load_config_empty_file(self, tmp_path):
        """Test loading empty YAML file raises ConfigValidationError."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        with pytest.raises(ConfigValidationError, match="Configuration file is empty"):
            load_config(str(config_file))

    def test_load_config_missing_required_fields(self, tmp_path):
        """Test loading config with missing required fields raises ConfigValidationError."""
        config_file = tmp_path / "incomplete.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key",
            }
        }
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ConfigValidationError, match="Configuration validation failed"):
            load_config(str(config_file))

    def test_load_config_invalid_transport_value(self, tmp_path):
        """Test loading config with invalid transport value raises ConfigValidationError."""
        config_file = tmp_path / "bad_transport.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "test-key",
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
            "mcp": {"transport": "websocket"},
        }
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(ConfigValidationError, match="Configuration validation failed"):
            load_config(str(config_file))

    def test_load_config_with_both_api_keys_provided(self, tmp_path):
        """Test loading config allows both api_key and api_key_env when literal key is present."""
        config_file = tmp_path / "both_keys.yaml"
        config_data = {
            "llm": {
                "provider": "openai",
                "api_key": "literal-key",
                "api_key_env": "ENV_KEY",
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
        config_file.write_text(yaml.dump(config_data))

        config = load_config(str(config_file))
        assert config.llm.api_key == "literal-key"
        assert config.llm.api_key_env == "ENV_KEY"

    def test_api_key_resolution_from_env(self, tmp_path):
        """Test API key resolution from environment variable."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("""
llm:
  provider: openai
  api_key_env: TEST_OPENAI_KEY
  skill_generation_model: gpt-4
  simulation_model: gpt-4
skills:
  folder: ./skills
sessions:
  max_messages: 100
  idle_timeout_seconds: 3600
  max_concurrent_queue_depth: 8
mcp:
  transport: sse
""")
        
        os.environ["TEST_OPENAI_KEY"] = "sk-test-key-123"
        try:
            config = load_config(str(config_file))
            assert config.llm.api_key == "sk-test-key-123"
            assert config.llm.api_key_env == "TEST_OPENAI_KEY"
        finally:
            del os.environ["TEST_OPENAI_KEY"]

    def test_api_key_missing_env_var(self, tmp_path):
        """Test error when environment variable is not set."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("""
llm:
  provider: openai
  api_key_env: MISSING_KEY
  skill_generation_model: gpt-4
  simulation_model: gpt-4
skills:
  folder: ./skills
sessions:
  max_messages: 100
  idle_timeout_seconds: 3600
  max_concurrent_queue_depth: 8
mcp:
  transport: sse
""")
        
        with pytest.raises(ConfigValidationError, match="api_key_env 'MISSING_KEY' is not set"):
            load_config(str(config_file))

    def test_api_base_resolution_from_env(self, tmp_path):
        """Test API base URL resolution from environment variable."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("""
llm:
  provider: openai
  api_key: sk-literal-key
  api_base_env: TEST_API_BASE
  skill_generation_model: gpt-4
  simulation_model: gpt-4
skills:
  folder: ./skills
sessions:
  max_messages: 100
  idle_timeout_seconds: 3600
  max_concurrent_queue_depth: 8
mcp:
  transport: sse
""")
        
        os.environ["TEST_API_BASE"] = "https://custom.api.com/v1"
        try:
            config = load_config(str(config_file))
            assert config.llm.api_base == "https://custom.api.com/v1"
            assert config.llm.api_base_env == "TEST_API_BASE"
        finally:
            del os.environ["TEST_API_BASE"]

# Made with Bob
