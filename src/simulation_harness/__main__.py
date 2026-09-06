"""Entry point for running the simulation harness as a module."""

import uvicorn

from simulation_harness.config.env_overrides import apply_env_overrides
from simulation_harness.config.env_source import resolve_config_path
from simulation_harness.config.settings import load_config


def main() -> None:
    """Start the simulation harness server using uvicorn."""
    # Resolve HARNESS_CONFIG_PATH: process env wins, then .env file, then default.
    config_path = resolve_config_path()

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
