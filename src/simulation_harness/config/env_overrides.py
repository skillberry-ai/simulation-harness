"""Apply HARNESS_* env-var overrides to a loaded HarnessConfig.

This layer exists so the YAML schema stays strict (extra="forbid") while still
letting Kubernetes inject runtime tweaks via env vars. The full list of
recognized variables is documented in deploy/README.md.
"""

import os

from .models import HarnessConfig, TransportType


def _int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from e


def _bool_env(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ValueError(f"{name} must be a boolean, got {raw!r}")


def apply_env_overrides(config: HarnessConfig) -> HarnessConfig:
    """Return a copy of ``config`` with HARNESS_* env vars applied.

    Recognized variables (all optional):
      HARNESS_SERVER_HOST, HARNESS_SERVER_PORT
      HARNESS_SKILLS_FOLDER
      HARNESS_LOG_LEVEL, HARNESS_LOG_DESTINATION
      HARNESS_MCP_TRANSPORT
      HARNESS_SESSIONS_MAX_MESSAGES, HARNESS_SESSIONS_IDLE_TIMEOUT_SECONDS,
      HARNESS_SESSIONS_MAX_CONCURRENT_QUEUE_DEPTH
      HARNESS_AUTOSTART_ENABLED, HARNESS_AUTOSTART_SIMULATION
    """
    data = config.model_dump()

    server_host = os.getenv("HARNESS_SERVER_HOST")
    if server_host is not None:
        data["server"]["host"] = server_host

    server_port = _int_env("HARNESS_SERVER_PORT")
    if server_port is not None:
        data["server"]["port"] = server_port

    skills_folder = os.getenv("HARNESS_SKILLS_FOLDER")
    if skills_folder is not None:
        data["skills"]["folder"] = skills_folder

    log_level = os.getenv("HARNESS_LOG_LEVEL")
    if log_level is not None:
        data["logging"]["level"] = log_level

    log_dest = os.getenv("HARNESS_LOG_DESTINATION")
    if log_dest is not None:
        data["logging"]["destination_folder"] = log_dest

    transport = os.getenv("HARNESS_MCP_TRANSPORT")
    if transport is not None:
        data["mcp"]["transport"] = TransportType(transport).value

    max_messages = _int_env("HARNESS_SESSIONS_MAX_MESSAGES")
    if max_messages is not None:
        data["sessions"]["max_messages"] = max_messages

    idle_timeout = _int_env("HARNESS_SESSIONS_IDLE_TIMEOUT_SECONDS")
    if idle_timeout is not None:
        data["sessions"]["idle_timeout_seconds"] = idle_timeout

    queue_depth = _int_env("HARNESS_SESSIONS_MAX_CONCURRENT_QUEUE_DEPTH")
    if queue_depth is not None:
        data["sessions"]["max_concurrent_queue_depth"] = queue_depth

    autostart_enabled = _bool_env("HARNESS_AUTOSTART_ENABLED")
    if autostart_enabled is not None:
        data["startup"]["autostart_enabled"] = autostart_enabled

    autostart = os.getenv("HARNESS_AUTOSTART_SIMULATION")
    if autostart is not None:
        data["startup"]["autostart_simulation"] = autostart

    overridden = HarnessConfig(**data)

    # Replace the cached singleton so get_config() returns the overridden values
    # everywhere (skill registry, dependency injection, etc.).
    from . import settings as _settings

    _settings._global_config = overridden

    return overridden


# Made with Bob
