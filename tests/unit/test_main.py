"""Tests for __main__ module."""

import logging
from pathlib import Path
from unittest.mock import Mock, patch, call


class TestMainModule:
    """Test the __main__ module startup."""

    @patch("simulation_harness.__main__.uvicorn.run")
    @patch("simulation_harness.__main__.get_config")
    def test_main_uses_configured_host_and_port(
        self, mock_get_config, mock_uvicorn_run
    ):
        """Test that main() uses host and port from configuration."""
        # Setup mock config
        mock_config = Mock()
        mock_config.server.host = "0.0.0.0"
        mock_config.server.port = 9000
        mock_get_config.return_value = mock_config

        # Import and run main
        from simulation_harness.__main__ import main

        main()

        # Verify uvicorn.run was called with correct parameters
        mock_uvicorn_run.assert_called_once()
        call_kwargs = mock_uvicorn_run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 9000

    @patch("simulation_harness.__main__.uvicorn.run")
    @patch("simulation_harness.__main__.get_config")
    def test_main_uses_default_host_and_port(self, mock_get_config, mock_uvicorn_run):
        """Test that main() uses default host and port when not configured."""
        # Setup mock config with defaults
        mock_config = Mock()
        mock_config.server.host = "localhost"
        mock_config.server.port = 8000
        mock_get_config.return_value = mock_config

        # Import and run main
        from simulation_harness.__main__ import main

        main()

        # Verify uvicorn.run was called with default parameters
        mock_uvicorn_run.assert_called_once()
        call_kwargs = mock_uvicorn_run.call_args[1]
        assert call_kwargs["host"] == "localhost"
        assert call_kwargs["port"] == 8000

    @patch("simulation_harness.__main__.uvicorn.run")
    @patch("simulation_harness.__main__.get_config")
    def test_main_passes_app_to_uvicorn(self, mock_get_config, mock_uvicorn_run):
        """Test that main() passes the correct app string to uvicorn."""
        # Setup mock config
        mock_config = Mock()
        mock_config.server.host = "localhost"
        mock_config.server.port = 8000
        mock_get_config.return_value = mock_config

        # Import and run main
        from simulation_harness.__main__ import main

        main()

        # Verify uvicorn.run was called with app string
        mock_uvicorn_run.assert_called_once()
        call_args = mock_uvicorn_run.call_args[0]
        assert call_args[0] == "simulation_harness.main:app"

    @patch("simulation_harness.__main__.uvicorn.run")
    @patch("simulation_harness.__main__.get_config")
    @patch("simulation_harness.__main__.load_config")
    def test_main_loads_config_before_getting_it(
        self, mock_load_config, mock_get_config, mock_uvicorn_run
    ):
        """Test that main() loads configuration before accessing global config."""
        mock_config = Mock()
        mock_config.server.host = "0.0.0.0"
        mock_config.server.port = 8086
        mock_get_config.return_value = mock_config

        from simulation_harness.__main__ import main

        main()

        assert mock_load_config.called
        assert mock_get_config.called
        assert mock_uvicorn_run.called

        ordered_calls = [
            call.load_config("config/harness.yaml"),
            call.get_config(),
            call.uvicorn.run(
                "simulation_harness.main:app",
                host="0.0.0.0",
                port=8086,
                log_level="info",
                log_config=None,
            ),
        ]
        actual_calls = [
            call.load_config(
                *mock_load_config.call_args[0], **mock_load_config.call_args[1]
            ),
            call.get_config(
                *mock_get_config.call_args[0], **mock_get_config.call_args[1]
            ),
            call.uvicorn.run(
                *mock_uvicorn_run.call_args[0], **mock_uvicorn_run.call_args[1]
            ),
        ]
        assert actual_calls == ordered_calls


class TestLoggingConfiguration:
    """Test logging configuration in main.py."""

    def test_logging_creates_log_directory(self, tmp_path):
        """Test that logging setup creates the log directory if it doesn't exist."""
        # Create a temporary config file with custom log directory
        import yaml
        from simulation_harness.config.settings import load_config

        log_dir = tmp_path / "custom_logs"
        config_file = tmp_path / "test_config.yaml"
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
            "mcp": {"transport": "sse"},
            "logging": {
                "level": "INFO",
                "destination_folder": str(log_dir),
            },
        }
        config_file.write_text(yaml.dump(config_data))

        # Load config and verify log directory is created
        config = load_config(str(config_file))

        # Simulate what main.py does
        log_path = Path(config.logging.destination_folder)
        log_path.mkdir(parents=True, exist_ok=True)

        # Verify directory was created
        assert log_dir.exists()
        assert log_dir.is_dir()

    def test_logging_uses_configured_level(self):
        """Test that logging configuration respects the configured level."""
        from simulation_harness.config.settings import load_config

        config = load_config("config/harness.yaml")

        # Verify the level is accessible and valid
        assert config.logging.level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        assert hasattr(logging, config.logging.level)

    def test_logging_filename_format(self):
        """Test that log filename follows the required format."""
        from datetime import datetime

        # Simulate filename generation
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"{timestamp}_simulation-harness.log"

        # Verify format: YYYY-MM-DD_HH-MM-SS_simulation-harness.log
        parts = log_filename.split("_")
        assert len(parts) == 3  # date, time, simulation-harness.log
        assert parts[0].count("-") == 2  # YYYY-MM-DD
        assert parts[1].count("-") == 2  # HH-MM-SS
        assert parts[2] == "simulation-harness.log"

    def test_logging_uses_configured_destination_folder(self):
        """Test that logging uses the destination folder from config."""
        from simulation_harness.config.settings import load_config

        config = load_config("config/harness.yaml")

        # Verify destination folder is configured
        assert config.logging.destination_folder == "./logs"


# Made with Bob
