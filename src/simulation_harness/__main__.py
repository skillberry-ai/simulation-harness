"""Entry point for running the simulation harness as a module."""

import os

import uvicorn
from dotenv import dotenv_values

from simulation_harness.config.settings import load_config


def main() -> None:
    """Start the simulation harness server using uvicorn."""
    # Resolve HARNESS_CONFIG_PATH: process env wins, then .env file, then default.
    _env_vars = dotenv_values(".env")
    config_path = os.getenv(
        "HARNESS_CONFIG_PATH",
        _env_vars.get("HARNESS_CONFIG_PATH", "config/harness.yaml"),
    )

    # Load config here to read host/port before uvicorn starts.
    # main.py calls load_config() again at import — that second call is idempotent.
    config = load_config(config_path)

    uvicorn.run(
        "simulation_harness.main:app",
        host=config.server.host,
        port=config.server.port,
        log_level="info",
        log_config=None,
    )


if __name__ == "__main__":
    main()


# Made with Bob
