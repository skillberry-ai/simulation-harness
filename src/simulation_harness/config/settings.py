"""Configuration loading and validation."""

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml
from pydantic import ValidationError

from .models import HarnessConfig

if TYPE_CHECKING:
    from .secrets import Secrets

_global_config: Optional[HarnessConfig] = None
_global_secrets: Optional["Secrets"] = None


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


def get_config() -> HarnessConfig:
    """Get the global non-secret configuration instance.

    Raises:
        RuntimeError: If configuration not loaded yet.
    """
    global _global_config
    if _global_config is None:
        raise RuntimeError("Configuration not loaded. Call load_config() first.")
    return _global_config


def get_secrets() -> "Secrets":
    """Get the global Secrets instance.

    Raises:
        RuntimeError: If secrets not loaded yet.
    """
    global _global_secrets
    if _global_secrets is None:
        raise RuntimeError("Secrets not loaded. Call load_secrets() first.")
    return _global_secrets


def load_config(config_path: str) -> HarnessConfig:
    """Load and validate non-secret configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Validated HarnessConfig instance (also stored as global).

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ConfigValidationError: If the config is invalid or fails validation.
    """
    global _global_config

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

    _global_config = config
    return config


def load_secrets(env_file: str | None = ".env") -> "Secrets":
    """Load and validate application secrets from environment.

    Clears the cached skill registry so the next get_skill_registry() call
    rebuilds it with the new credentials.

    Args:
        env_file: Path to a dotenv file to read in addition to process env.
            Pass None to disable .env loading entirely (useful for tests).

    Returns:
        Validated Secrets instance (also stored as global).

    Raises:
        pydantic.ValidationError: If required secrets are missing or invalid.
    """
    global _global_secrets
    from .secrets import Secrets

    secrets = Secrets(_env_file=env_file)  # type: ignore[arg-type]
    _global_secrets = secrets

    # Invalidate the cached skill registry — it holds a SkillGenerator built
    # with the old key and will be rebuilt on next get_skill_registry() call.
    try:
        from simulation_harness.api.dependencies import reset_skill_registry as _reset
        _reset()
    except ImportError:
        pass  # dependencies module not yet imported — nothing to invalidate

    return secrets


# Made with Bob
