"""Apply HARNESS_* env-var overrides to a loaded HarnessConfig.

This layer exists so the YAML schema stays strict (extra="forbid") while still
letting Kubernetes inject runtime tweaks via env vars. The full list of
recognized variables is documented in deploy/README.md.

Each variable is resolved through `config.env_source`: the process environment
wins, then the dotenv file, then the YAML value stands. `.env` is consulted
because `.env.example` documents `HARNESS_LLM_*` as belonging there; before
that ingress existed, a `.env`-only override was silently discarded and the
YAML model reached the gateway instead (issue #13).
"""

import os
from typing import Any, Callable, Sequence

from .env_source import DEFAULT_ENV_FILE, dotenv_snapshot, env_value
from .models import HarnessConfig, TransportType

# Variables that belong in `.env` but are not config overrides, so the typo
# check below must not flag them: secrets (config/secrets.py owns those), the
# path to the YAML itself, and the gateway cache toggle read by
# skills/generation/llm.py.
_NON_OVERRIDE_KEYS = frozenset(
    {"HARNESS_CONFIG_PATH", "HARNESS_LLM_NO_CACHE"},
)

_PROCESS_ENV_SOURCE = "process env"


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from e


def _parse_bool(name: str, raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ValueError(f"{name} must be a boolean, got {raw!r}")


def _parse_str(name: str, raw: str) -> str:  # noqa: ARG001 - uniform parser signature
    return raw


def _parse_transport(name: str, raw: str) -> str:
    return TransportType(raw).value


# (env var, path into the config dict, parser). The llm: block is overridable
# because an orchestrator may deploy the image without mounting a harness.yaml
# ConfigMap, leaving the baked-in models as the only ones reachable. provider is
# included alongside the model names: the provider and the model prefix must
# stay consistent with the endpoint LLM_API_BASE points at, so overriding one
# without the other is a trap.
_OVERRIDES: Sequence[tuple[str, tuple[str, str], Callable[[str, str], Any]]] = (
    ("HARNESS_LLM_PROVIDER", ("llm", "provider"), _parse_str),
    (
        "HARNESS_LLM_SKILL_GENERATION_MODEL",
        ("llm", "skill_generation_model"),
        _parse_str,
    ),
    ("HARNESS_LLM_SIMULATION_MODEL", ("llm", "simulation_model"), _parse_str),
    ("HARNESS_SERVER_HOST", ("server", "host"), _parse_str),
    ("HARNESS_SERVER_PORT", ("server", "port"), _parse_int),
    ("HARNESS_SKILLS_FOLDER", ("skills", "folder"), _parse_str),
    ("HARNESS_LOG_LEVEL", ("logging", "level"), _parse_str),
    ("HARNESS_LOG_DESTINATION", ("logging", "destination_folder"), _parse_str),
    ("HARNESS_MCP_TRANSPORT", ("mcp", "transport"), _parse_transport),
    ("HARNESS_SESSIONS_MAX_MESSAGES", ("sessions", "max_messages"), _parse_int),
    (
        "HARNESS_SESSIONS_IDLE_TIMEOUT_SECONDS",
        ("sessions", "idle_timeout_seconds"),
        _parse_int,
    ),
    (
        "HARNESS_SESSIONS_MAX_CONCURRENT_QUEUE_DEPTH",
        ("sessions", "max_concurrent_queue_depth"),
        _parse_int,
    ),
    ("HARNESS_AUTOSTART_ENABLED", ("startup", "autostart_enabled"), _parse_bool),
    ("HARNESS_AUTOSTART_SIMULATION", ("startup", "autostart_simulation"), _parse_str),
)

RECOGNIZED_KEYS = frozenset(name for name, _, _ in _OVERRIDES) | _NON_OVERRIDE_KEYS

# What the last apply_env_overrides() call actually did. Recorded rather than
# logged inline: main.py configures logging *from* the overridden config, so no
# logger exists yet at the point the overrides are applied.
_applied: dict[str, tuple[str, str]] = {}
_unrecognized: list[str] = []


def applied_overrides() -> dict[str, tuple[str, str]]:
    """Overrides applied by the last call: name -> (value, source)."""
    return dict(_applied)


def unrecognized_dotenv_keys() -> list[str]:
    """HARNESS_* keys found in the dotenv file that no override consumes.

    Almost always a typo (``HARNESS_LLM_MODEL`` for
    ``HARNESS_LLM_SIMULATION_MODEL``), which would otherwise be indistinguishable
    from not having set it at all. Sorted, so the logged line is stable.
    """
    return list(_unrecognized)


def apply_env_overrides(
    config: HarnessConfig, *, env_file: str | None = DEFAULT_ENV_FILE
) -> HarnessConfig:
    """Return a copy of ``config`` with HARNESS_* overrides applied.

    Precedence per variable: process environment, then ``env_file``, then the
    value already in ``config``. Pass ``env_file=None`` to ignore the dotenv
    file entirely.

    Recognized variables (all optional):
      HARNESS_SERVER_HOST, HARNESS_SERVER_PORT
      HARNESS_SKILLS_FOLDER
      HARNESS_LOG_LEVEL, HARNESS_LOG_DESTINATION
      HARNESS_MCP_TRANSPORT
      HARNESS_SESSIONS_MAX_MESSAGES, HARNESS_SESSIONS_IDLE_TIMEOUT_SECONDS,
      HARNESS_SESSIONS_MAX_CONCURRENT_QUEUE_DEPTH
      HARNESS_AUTOSTART_ENABLED, HARNESS_AUTOSTART_SIMULATION
      HARNESS_LLM_PROVIDER, HARNESS_LLM_SKILL_GENERATION_MODEL,
      HARNESS_LLM_SIMULATION_MODEL

    Raises:
        ValueError: If a variable is set to a value of the wrong type, whether
            it came from the process environment or from ``env_file``.
    """
    global _applied, _unrecognized

    snapshot = dotenv_snapshot(env_file)
    data = config.model_dump()
    applied: dict[str, tuple[str, str]] = {}

    for name, (section, field), parse in _OVERRIDES:
        raw = env_value(name, snapshot)
        if raw is None:
            continue
        data[section][field] = parse(name, raw)
        source = _PROCESS_ENV_SOURCE if name in os.environ else str(env_file)
        applied[name] = (raw, source)

    overridden = HarnessConfig(**data)

    _applied = applied
    _unrecognized = sorted(
        key
        for key in snapshot
        if key.startswith("HARNESS_") and key not in RECOGNIZED_KEYS
    )

    # Replace the cached singleton so get_config() returns the overridden values
    # everywhere (skill registry, dependency injection, etc.).
    from . import settings as _settings

    _settings._global_config = overridden

    return overridden


# Made with Bob
