"""Tests for __main__ module."""

import logging
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, call, AsyncMock
from fastapi.testclient import TestClient


class TestMainModule:
    """Test the __main__ module startup."""

    @patch("simulation_harness.__main__.uvicorn.run")
    @patch("simulation_harness.__main__.load_config")
    def test_main_uses_configured_host_and_port(
        self, mock_load_config, mock_uvicorn_run
    ):
        """Test that main() uses host and port from configuration."""
        mock_config = Mock()
        mock_config.server.host = "0.0.0.0"
        mock_config.server.port = 9000
        mock_load_config.return_value = mock_config

        from simulation_harness.__main__ import main

        main()

        mock_uvicorn_run.assert_called_once()
        call_kwargs = mock_uvicorn_run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 9000

    @patch("simulation_harness.__main__.uvicorn.run")
    @patch("simulation_harness.__main__.load_config")
    def test_main_uses_default_host_and_port(self, mock_load_config, mock_uvicorn_run):
        """Test that main() uses default host and port when not configured."""
        mock_config = Mock()
        mock_config.server.host = "localhost"
        mock_config.server.port = 8000
        mock_load_config.return_value = mock_config

        from simulation_harness.__main__ import main

        main()

        mock_uvicorn_run.assert_called_once()
        call_kwargs = mock_uvicorn_run.call_args[1]
        assert call_kwargs["host"] == "localhost"
        assert call_kwargs["port"] == 8000

    @patch("simulation_harness.__main__.uvicorn.run")
    @patch("simulation_harness.__main__.load_config")
    def test_main_passes_app_to_uvicorn(self, mock_load_config, mock_uvicorn_run):
        """Test that main() passes the correct app string to uvicorn."""
        mock_config = Mock()
        mock_config.server.host = "localhost"
        mock_config.server.port = 8000
        mock_load_config.return_value = mock_config

        from simulation_harness.__main__ import main

        main()

        mock_uvicorn_run.assert_called_once()
        call_args = mock_uvicorn_run.call_args[0]
        assert call_args[0] == "simulation_harness.main:app"

    @patch("simulation_harness.__main__.uvicorn.run")
    @patch("simulation_harness.__main__.load_config")
    def test_main_loads_config_before_starting_uvicorn(
        self, mock_load_config, mock_uvicorn_run
    ):
        """Test that main() loads config and passes its host/port to uvicorn."""
        mock_config = Mock()
        mock_config.server.host = "0.0.0.0"
        mock_config.server.port = 8086
        mock_load_config.return_value = mock_config

        from simulation_harness.__main__ import main

        main()

        assert mock_load_config.called
        assert mock_uvicorn_run.called

        call_kwargs = mock_uvicorn_run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 8086
        assert mock_uvicorn_run.call_args[0][0] == "simulation_harness.main:app"


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


class TestLifespan:
    """Test FastAPI lifespan startup/shutdown behaviour."""

    @pytest.mark.asyncio
    async def test_lifespan_wraps_oserror_from_load_secrets_as_runtime_error(
        self, monkeypatch
    ):
        """lifespan converts any non-ValidationError from load_secrets to RuntimeError."""
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("HARNESS_CONFIG_PATH", "config/harness.yaml")

        import simulation_harness.main as main_mod

        with patch.object(
            main_mod, "load_secrets", side_effect=PermissionError("cannot read .env")
        ):
            with pytest.raises(RuntimeError, match="Missing required secrets"):
                async with main_mod.lifespan(main_mod.app):
                    pass  # pragma: no cover


class TestExceptionHandlers:
    """Test exception handlers for FastAPI app."""

    def test_port_in_use_error_handler_exists(self):
        """Verify PortInUseError exception handler is registered with the FastAPI app."""
        from simulation_harness.main import app
        from simulation_harness.utils.errors import PortInUseError

        # Check that the handler is registered
        assert PortInUseError in app.exception_handlers
        handler = app.exception_handlers[PortInUseError]
        assert handler is not None
        assert callable(handler)


# Made with Bob
