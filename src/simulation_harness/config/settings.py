"""Configuration loading and validation."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from .models import HarnessConfig

# Global configuration instance
_global_config: Optional[HarnessConfig] = None
_dotenv_loaded: bool = False


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


def get_config() -> HarnessConfig:
    """Get the global configuration instance.

    Returns:
        Global HarnessConfig instance

    Raises:
        RuntimeError: If configuration not loaded yet
    """
    global _global_config
    if _global_config is None:
        raise RuntimeError("Configuration not loaded. Call load_config() first.")
    return _global_config


def load_config(config_path: str) -> HarnessConfig:
    """
    Load and validate configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        Validated HarnessConfig instance

    Raises:
        FileNotFoundError: If the config file doesn't exist
        ConfigValidationError: If the config is invalid or fails validation
    """
    global _global_config, _dotenv_loaded

    if not _dotenv_loaded:
        from dotenv import load_dotenv
        load_dotenv(override=False)
        _dotenv_loaded = True

    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    try:
        with open(path, "r") as f:
            config_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigValidationError(f"Failed to parse YAML: {e}") from e

    if config_data is None:
        raise ConfigValidationError("Configuration file is empty")

    try:
        config = HarnessConfig(**config_data)
    except ValidationError as e:
        raise ConfigValidationError(f"Configuration validation failed: {e}") from e

    _validate_resolved_llm_config(config)

    # Store as global config
    _global_config = config

    return config


def _validate_resolved_llm_config(config: HarnessConfig) -> None:
    """Resolve environment-backed LLM settings at startup."""
    resolved_api_key = os.getenv(config.llm.api_key_env)
    if not resolved_api_key:
        raise ConfigValidationError(
            f"Configuration validation failed: api_key_env '{config.llm.api_key_env}' is not set or empty"
        )
    config.llm._resolved_api_key = resolved_api_key

    if config.llm.api_base is None and config.llm.api_base_env is not None:
        resolved_api_base = os.getenv(config.llm.api_base_env)
        if not resolved_api_base:
            raise ConfigValidationError(
                f"Configuration validation failed: api_base_env '{config.llm.api_base_env}' is not set or empty"
            )
        config.llm.api_base = resolved_api_base


# Made with Bob
