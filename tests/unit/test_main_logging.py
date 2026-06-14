"""Tests for main.py logging configuration with uvicorn."""

import logging
import os
from unittest.mock import MagicMock, patch


def test_uvicorn_respects_logging_config():
    """Test that uvicorn.run is configured to respect our logging setup.

    This test verifies that uvicorn.run is called with log_config=None,
    which prevents uvicorn from overriding our logging configuration.
    Without this, uvicorn's default logging config would interfere with
    our file handler, causing API request logs to not be written to the log file.
    """
    with patch("simulation_harness.__main__.uvicorn.run") as mock_run:
        with (
            patch("simulation_harness.__main__.load_config") as mock_load,
            patch(
                "simulation_harness.__main__.apply_env_overrides",
                side_effect=lambda c: c,
            ),
        ):
            mock_config = MagicMock()
            mock_config.server.host = "0.0.0.0"
            mock_config.server.port = 8000
            mock_load.return_value = mock_config

            from simulation_harness.__main__ import main

            main()

            # Verify uvicorn.run was called with log_config=None
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args.kwargs

            # The critical assertion: log_config must be None
            # to prevent uvicorn from overriding our logging configuration
            assert "log_config" in call_kwargs, (
                "uvicorn.run must be called with log_config parameter"
            )
            assert call_kwargs["log_config"] is None, (
                "uvicorn.run must use log_config=None to preserve our logging setup. "
                "Without this, uvicorn's default logging config interferes with our "
                "file handler, causing API request logs to not be written to the log file."
            )


def test_logging_configured_before_uvicorn():
    """Test that logging is configured in main.py before uvicorn starts.

    This ensures that when uvicorn imports main.py, the logging configuration
    is already in place and will be used by all request handlers.
    """
    # This test verifies the module-level logging setup in main.py
    # by checking that the logger is configured when the module is imported

    with patch.dict(
        os.environ,
        {"HARNESS_CONFIG_PATH": "config/harness.yaml", "LLM_API_KEY": "test-key"},
    ):
        # Import main.py (this triggers module-level logging setup)
        import simulation_harness.main as main_module

        # Verify logger exists and is configured
        assert hasattr(main_module, "logger")
        assert isinstance(main_module.logger, logging.Logger)

        # Verify logging has handlers (console + file)
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) >= 2, (
            "Expected at least 2 handlers (console + file)"
        )

        # Verify at least one FileHandler exists
        file_handlers = [
            h for h in root_logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) > 0, (
            "Expected at least one FileHandler to be configured"
        )


# Made with Bob
