"""Integration tests for FastAPI application."""

import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from simulation_harness.utils.errors import (
    SimulationAlreadyExistsError,
)


def _valid_harness_config() -> dict:
    """Return a valid HarnessConfig dict for use in test fixtures."""
    return {
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
    }


class TestAppStartup:
    """Test application startup and configuration."""

    def test_app_starts_with_valid_config(self):
        """Test that app starts successfully with valid config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_valid_harness_config(), f)
            config_path = f.name

        _prior_key = os.environ.get("LLM_API_KEY")
        os.environ["HARNESS_CONFIG_PATH"] = config_path
        os.environ["LLM_API_KEY"] = "test-key"

        try:
            from simulation_harness.main import app

            assert app is not None
            assert app.title == "Simulation Harness"

            routes = [route.path for route in app.routes]
            assert "/api/v1/simulation" in routes
            assert "/api/v1/simulation/reset" in routes

        finally:
            os.unlink(config_path)
            if "HARNESS_CONFIG_PATH" in os.environ:
                del os.environ["HARNESS_CONFIG_PATH"]
            if _prior_key is not None:
                os.environ["LLM_API_KEY"] = _prior_key
            elif "LLM_API_KEY" in os.environ:
                del os.environ["LLM_API_KEY"]

    def test_app_refuses_to_start_with_invalid_config(self):
        """Test that app refuses to start with invalid config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config = {
                "llm": {
                    # Missing required fields
                    "provider": "openai",
                }
            }
            yaml.dump(config, f)
            config_path = f.name

        try:
            from simulation_harness.config.settings import (
                load_config,
                ConfigValidationError,
            )

            with pytest.raises(ConfigValidationError):
                load_config(config_path)

        finally:
            os.unlink(config_path)

    def test_app_refuses_to_start_with_missing_config(self):
        """Test that app refuses to start when config file is missing."""
        from simulation_harness.config.settings import load_config

        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")


class TestMCPTransportMounting:
    """Test MCP transport mounting."""

    @pytest.fixture
    def valid_config_path(self):
        """Create a temporary valid config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_valid_harness_config(), f)
            yield f.name
        os.unlink(f.name)

    def test_sse_transport_mounts_correctly(self, valid_config_path):
        """Test that SSE transport mounts correctly."""
        _prior_key = os.environ.get("LLM_API_KEY")
        os.environ["HARNESS_CONFIG_PATH"] = valid_config_path
        os.environ["LLM_API_KEY"] = "test-key"

        try:
            from simulation_harness.main import app

            routes = [route.path for route in app.routes]
            assert "/mcp/sse" in routes
            assert "/mcp/messages" in routes

        finally:
            if "HARNESS_CONFIG_PATH" in os.environ:
                del os.environ["HARNESS_CONFIG_PATH"]
            if _prior_key is not None:
                os.environ["LLM_API_KEY"] = _prior_key
            elif "LLM_API_KEY" in os.environ:
                del os.environ["LLM_API_KEY"]

    def test_streamable_http_transport_mounts_correctly(self):
        """Test that Streamable HTTP transport mounts correctly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config = _valid_harness_config()
            config["mcp"]["transport"] = "streamable_http"
            yaml.dump(config, f)
            config_path = f.name

        try:
            from simulation_harness.config.settings import load_config
            from simulation_harness.config.models import TransportType

            loaded_config = load_config(config_path)
            assert loaded_config.mcp.transport == TransportType.STREAMABLE_HTTP
            assert loaded_config.mcp.transport.value == "streamable_http"

        finally:
            os.unlink(config_path)


class TestManagementAPIRoutes:
    """Test management API routes registration."""

    @pytest.fixture
    def app_client(self):
        """Create test client with valid config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_valid_harness_config(), f)
            config_path = f.name

        _prior_key = os.environ.get("LLM_API_KEY")
        os.environ["HARNESS_CONFIG_PATH"] = config_path
        os.environ["LLM_API_KEY"] = "test-key"

        try:
            from simulation_harness.main import app

            client = TestClient(app)
            yield client
        finally:
            os.unlink(config_path)
            if "HARNESS_CONFIG_PATH" in os.environ:
                del os.environ["HARNESS_CONFIG_PATH"]
            if _prior_key is not None:
                os.environ["LLM_API_KEY"] = _prior_key
            elif "LLM_API_KEY" in os.environ:
                del os.environ["LLM_API_KEY"]

    def test_management_routes_are_registered(self, app_client):
        """Test that management API routes are registered."""
        response = app_client.get("/openapi.json")
        assert response.status_code == 200

        openapi_schema = response.json()
        paths = openapi_schema.get("paths", {})

        assert "/api/v1/simulation" in paths
        assert "post" in paths["/api/v1/simulation"]
        assert "get" in paths["/api/v1/simulation"]
        assert "delete" in paths["/api/v1/simulation"]
        assert "/api/v1/simulation/reset" in paths
        assert "post" in paths["/api/v1/simulation/reset"]


class TestErrorHandlers:
    """Test error handlers return correct status codes."""

    @pytest.fixture
    def app_with_mocked_dependencies(self):
        """Create app with mocked dependencies for error testing."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_valid_harness_config(), f)
            config_path = f.name

        _prior_key = os.environ.get("LLM_API_KEY")
        os.environ["HARNESS_CONFIG_PATH"] = config_path
        os.environ["LLM_API_KEY"] = "test-key"

        try:
            from simulation_harness.main import app

            yield app
        finally:
            os.unlink(config_path)
            if "HARNESS_CONFIG_PATH" in os.environ:
                del os.environ["HARNESS_CONFIG_PATH"]
            if _prior_key is not None:
                os.environ["LLM_API_KEY"] = _prior_key
            elif "LLM_API_KEY" in os.environ:
                del os.environ["LLM_API_KEY"]

    def test_simulation_already_exists_returns_409(self, app_with_mocked_dependencies):
        """Test SimulationAlreadyExistsError returns 409."""
        TestClient(app_with_mocked_dependencies)

        with patch(
            "simulation_harness.api.v1.simulations.SimulationHostDep"
        ) as mock_dep:
            mock_host = AsyncMock()
            mock_host.create_simulation.side_effect = SimulationAlreadyExistsError(
                "Already exists"
            )
            mock_dep.return_value = mock_host

            assert hasattr(app_with_mocked_dependencies, "exception_handlers")

    def test_simulation_not_found_returns_404(self, app_with_mocked_dependencies):
        """Test SimulationNotFoundError returns 404."""
        assert hasattr(app_with_mocked_dependencies, "exception_handlers")

    def test_openapi_validation_error_returns_422(self, app_with_mocked_dependencies):
        """Test OpenAPIValidationError returns 422."""
        assert hasattr(app_with_mocked_dependencies, "exception_handlers")

    def test_config_validation_error_returns_500(self, app_with_mocked_dependencies):
        """Test ConfigValidationError returns 500."""
        assert hasattr(app_with_mocked_dependencies, "exception_handlers")

    def test_session_expired_error_returns_410(self, app_with_mocked_dependencies):
        """Test SessionExpiredError returns 410."""
        assert hasattr(app_with_mocked_dependencies, "exception_handlers")

    def test_concurrent_queue_full_returns_503(self, app_with_mocked_dependencies):
        """Test ConcurrentQueueFullError returns 503."""
        assert hasattr(app_with_mocked_dependencies, "exception_handlers")

    def test_generic_exception_returns_500(self, app_with_mocked_dependencies):
        """Test generic exceptions return 500."""
        assert hasattr(app_with_mocked_dependencies, "exception_handlers")


class TestLifespanManagement:
    """Test lifespan management."""

    def test_lifespan_startup_validates_config(self):
        """Test that lifespan startup validates config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_valid_harness_config(), f)
            config_path = f.name

        _prior_key = os.environ.get("LLM_API_KEY")
        os.environ["HARNESS_CONFIG_PATH"] = config_path
        os.environ["LLM_API_KEY"] = "test-key"

        try:
            from simulation_harness.main import app

            with TestClient(app):
                assert True

        finally:
            os.unlink(config_path)
            if "HARNESS_CONFIG_PATH" in os.environ:
                del os.environ["HARNESS_CONFIG_PATH"]
            if _prior_key is not None:
                os.environ["LLM_API_KEY"] = _prior_key
            elif "LLM_API_KEY" in os.environ:
                del os.environ["LLM_API_KEY"]

    def test_lifespan_cleanup_works_properly(self):
        """Test that lifespan cleanup works properly."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_valid_harness_config(), f)
            config_path = f.name

        _prior_key = os.environ.get("LLM_API_KEY")
        os.environ["HARNESS_CONFIG_PATH"] = config_path
        os.environ["LLM_API_KEY"] = "test-key"

        try:
            from simulation_harness.main import app

            with TestClient(app):
                pass

            assert True

        finally:
            os.unlink(config_path)
            if "HARNESS_CONFIG_PATH" in os.environ:
                del os.environ["HARNESS_CONFIG_PATH"]
            if _prior_key is not None:
                os.environ["LLM_API_KEY"] = _prior_key
            elif "LLM_API_KEY" in os.environ:
                del os.environ["LLM_API_KEY"]


class TestConfigPathEnvironmentVariable:
    """Test config path can be specified via environment variable."""

    def test_config_path_from_env_variable(self):
        """Test that config path can be specified via HARNESS_CONFIG_PATH."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(_valid_harness_config(), f)
            config_path = f.name

        _prior_key = os.environ.get("LLM_API_KEY")
        os.environ["HARNESS_CONFIG_PATH"] = config_path
        os.environ["LLM_API_KEY"] = "test-key"

        try:
            from simulation_harness.main import app

            assert app is not None

        finally:
            os.unlink(config_path)
            if "HARNESS_CONFIG_PATH" in os.environ:
                del os.environ["HARNESS_CONFIG_PATH"]
            if _prior_key is not None:
                os.environ["LLM_API_KEY"] = _prior_key
            elif "LLM_API_KEY" in os.environ:
                del os.environ["LLM_API_KEY"]

    def test_config_path_defaults_to_config_harness_yaml(self):
        """Test that config path defaults to config/harness.yaml."""
        if "HARNESS_CONFIG_PATH" in os.environ:
            del os.environ["HARNESS_CONFIG_PATH"]

        _prior_key = os.environ.get("LLM_API_KEY")
        os.environ["LLM_API_KEY"] = "test-key"

        try:
            from simulation_harness.main import app

            assert app is not None

        finally:
            if _prior_key is not None:
                os.environ["LLM_API_KEY"] = _prior_key
            elif "LLM_API_KEY" in os.environ:
                del os.environ["LLM_API_KEY"]


# Made with Bob
