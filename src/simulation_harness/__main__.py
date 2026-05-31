"""Entry point for running the simulation harness as a module."""

import uvicorn

import os

from simulation_harness.config.settings import get_config, load_config


def main() -> None:
    """Start the simulation harness server using uvicorn."""
    config_path = os.getenv("HARNESS_CONFIG_PATH", "config/harness.yaml")
    load_config(config_path)
    config = get_config()
    
    uvicorn.run(
        "simulation_harness.main:app",
        host=config.server.host,
        port=config.server.port,
        log_level="info",
        log_config=None,  # Disable uvicorn's logging config to preserve our setup
    )


if __name__ == "__main__":
    main()


# Made with Bob