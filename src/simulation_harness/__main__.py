"""Entry point for running the simulation harness as a module."""

import os

import uvicorn
from dotenv import dotenv_values

from simulation_harness.config.env_overrides import apply_env_overrides
from simulation_harness.config.settings import load_config


def main() -> None:
    """Start the simulation harness server using uvicorn."""
    # Resolve HARNESS_CONFIG_PATH: process env wins, then .env file, then default.
    _env_vars = dotenv_values(".env")
    config_path = os.getenv(
        "HARNESS_CONFIG_PATH",
        _env_vars.get("HARNESS_CONFIG_PATH", "config/harness.yaml"),
    )

    # Load YAML, then apply HARNESS_* env-var overrides (k8s injects these).
    config = load_config(config_path)
    config = apply_env_overrides(config)

    # 30s gives in-flight tool calls time to drain before uvicorn force-closes.
    uvicorn.run(
        "simulation_harness.main:app",
        host=config.server.host,
        port=config.server.port,
        log_level="info",
        log_config=None,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()


# Made with Bob
