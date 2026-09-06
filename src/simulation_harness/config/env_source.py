"""Single ingress point for HARNESS_* configuration variables.

Resolution order for every recognized variable is: the process environment
first, then a dotenv file, then the caller's default. Kubernetes injects an
`env:` block, so the process environment must win; local development keeps its
settings in `.env` next to `.env.example`, so `.env` has to be consulted too.

Deliberately reads `.env` without mutating ``os.environ``: `load_dotenv()`
would leak every key in the file into unrelated readers of the process
environment and is far harder to scope in tests. Nothing here is cached — a
snapshot keyed on the relative path ``.env`` would go stale across a chdir,
and the file is read a handful of times per process, so a cache would buy
nothing and cost correctness.

Secrets do NOT come through here; `config/secrets.py` remains their only
ingress.
"""

import os
from typing import Mapping

from dotenv import dotenv_values

DEFAULT_ENV_FILE = ".env"
DEFAULT_CONFIG_PATH = "config/harness.yaml"


def dotenv_snapshot(env_file: str | None) -> dict[str, str]:
    """Read ``env_file`` into a dict, or return an empty one.

    An absent file and ``env_file=None`` both yield ``{}``. Keys written
    without a value (a bare ``FOO`` line) parse to ``None`` and are dropped, so
    they cannot shadow a real process-environment value.
    """
    if env_file is None:
        return {}
    return {k: v for k, v in dotenv_values(env_file).items() if v is not None}


def env_value(name: str, snapshot: Mapping[str, str]) -> str | None:
    """Return ``name`` from the process environment, else from ``snapshot``.

    An empty string in the process environment is returned verbatim: emptying a
    variable is a deliberate act, not a reason to fall through to the file.
    """
    value = os.environ.get(name)
    if value is not None:
        return value
    return snapshot.get(name)


def harness_env(name: str, *, env_file: str | None = DEFAULT_ENV_FILE) -> str | None:
    """One-off lookup of ``name`` for callers that need a single variable."""
    return env_value(name, dotenv_snapshot(env_file))


def resolve_config_path(*, env_file: str | None = DEFAULT_ENV_FILE) -> str:
    """Resolve the harness YAML path: process env, then ``env_file``, then default."""
    return harness_env("HARNESS_CONFIG_PATH", env_file=env_file) or DEFAULT_CONFIG_PATH


# Made with Bob
