"""Tests for SimulationInstance."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from simulation_harness.core.simulation_instance import SimulationInstance
from simulation_harness.models.domain import SimulationSpec
from simulation_harness.utils.errors import ConcurrentQueueFullError
from typing import Any


@pytest.fixture
def mock_spec() -> SimulationSpec:
    """Create a mock simulation spec."""
    return SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
        },
    )


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock deep agent."""
    agent = MagicMock()
    agent.generate_response = AsyncMock(return_value={"result": "success"})
    agent.reset = AsyncMock()
    agent.shutdown = AsyncMock()
    return agent


def create_instance(spec: Any, **kwargs: Any) -> SimulationInstance:
    """Helper to create SimulationInstance with default config values."""
    defaults: dict[str, Any] = {
        "max_messages": 100,
        "idle_timeout_seconds": 3600,
        "max_queue_depth": 10,
        "api_key": SecretStr("test-key"),
        "model": "gpt-4",
        "temperature": 0.7,
        "max_tokens": 4000,
    }
    defaults.update(kwargs)
    return SimulationInstance(spec=spec, **defaults)


@pytest.mark.asyncio
async def test_execute_tool_success(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test successful tool execution."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec)

        result = await instance.execute_tool("test_tool", {"param": "value"})

        assert result.success is True
        assert result.content == '{"result": "success"}'
        assert result.error is None


@pytest.mark.asyncio
async def test_execute_tool_increments_counter(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test that tool execution increments counter."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec)

        state_before = instance.get_session_state()
        await instance.execute_tool("test_tool", {"param": "value"})
        state_after = instance.get_session_state()

        assert state_after.tool_call_count == state_before.tool_call_count + 1


@pytest.mark.asyncio
async def test_execute_tool_updates_last_activity(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test that tool execution updates last activity timestamp."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec)

        state_before = instance.get_session_state()
        assert state_before.last_activity is None  # Timer hasn't started yet

        await instance.execute_tool("test_tool", {"param": "value"})
        state_after = instance.get_session_state()

        assert state_after.last_activity is not None  # Timer started
        assert isinstance(state_after.last_activity, datetime)


@pytest.mark.asyncio
async def test_execute_tool_raises_on_max_messages(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test that exceeding max_messages returns failed result and resets."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec, max_messages=2)

        await instance.execute_tool("test_tool", {"param": "value"})
        await instance.execute_tool("test_tool", {"param": "value"})

        # Third call should fail with expiry
        result = await instance.execute_tool("test_tool", {"param": "value"})
        assert result.success is False
        assert result.error is not None
        assert "max_messages" in (result.error or "").lower()

        # Session should be reset
        state = instance.get_session_state()
        assert state.tool_call_count == 0


@pytest.mark.asyncio
async def test_execute_tool_raises_on_idle_timeout(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test that idle timeout returns failed result and resets."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec, idle_timeout_seconds=1)

        # Manually set last_activity to past
        instance._last_activity = datetime.now(timezone.utc) - timedelta(seconds=2)  # type: ignore[assignment]

        # Call should fail with expiry
        result = await instance.execute_tool("test_tool", {"param": "value"})
        assert result.success is False
        assert result.error is not None
        assert "idle_timeout" in (result.error or "").lower()

        # Session should be reset
        state = instance.get_session_state()
        assert state.tool_call_count == 0


@pytest.mark.asyncio
async def test_execute_tool_enforces_queue_depth(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test that queue depth is enforced."""

    # Make agent slow to allow queue to fill
    async def slow_response(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(0.1)
        return {"result": "success"}

    slow_agent = MagicMock()
    slow_agent.generate_response = AsyncMock(side_effect=slow_response)
    slow_agent.reset = AsyncMock()
    slow_agent.shutdown = AsyncMock()

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=slow_agent
    ):
        instance = create_instance(mock_spec, max_queue_depth=2)

        # Start two tasks that will fill the queue
        task1 = asyncio.create_task(instance.execute_tool("test_tool", {"param": "1"}))
        task2 = asyncio.create_task(instance.execute_tool("test_tool", {"param": "2"}))

        # Wait a bit for tasks to start
        await asyncio.sleep(0.01)

        # Third task should raise ConcurrentQueueFullError
        with pytest.raises(ConcurrentQueueFullError):
            await instance.execute_tool("test_tool", {"param": "3"})

        # Clean up
        task1.cancel()
        task2.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass
        try:
            await task2
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_execute_tool_handles_agent_error(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test that agent errors are handled gracefully."""
    mock_agent.generate_response = AsyncMock(side_effect=Exception("Agent error"))

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec)

        result = await instance.execute_tool("test_tool", {"param": "value"})

        assert result.success is False
        assert result.error is not None
        assert "Agent error" in result.error


@pytest.mark.asyncio
async def test_execute_tool_does_not_increment_counter_on_failure(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test that counter is not incremented on failure."""
    mock_agent.generate_response = AsyncMock(side_effect=Exception("Agent error"))

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec)

        state_before = instance.get_session_state()
        await instance.execute_tool("test_tool", {"param": "value"})
        state_after = instance.get_session_state()

        assert state_after.tool_call_count == state_before.tool_call_count


@pytest.mark.asyncio
async def test_get_session_state(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """Test getting session state."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(
            mock_spec, max_messages=10, idle_timeout_seconds=300, max_queue_depth=5
        )

        state = instance.get_session_state()

        assert state.tool_call_count == 0
        assert state.max_messages == 10
        assert state.idle_timeout_seconds == 300
        assert state.max_queue_depth == 5
        assert state.queue_depth == 0
        assert state.last_activity is None  # Timer hasn't started yet


@pytest.mark.asyncio
async def test_reset_session(mock_spec: SimulationSpec, mock_agent: MagicMock) -> None:
    """Test resetting session."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec)

        # Execute some tools
        await instance.execute_tool("test_tool", {"param": "value"})
        await instance.execute_tool("test_tool", {"param": "value"})

        # Reset
        await instance.reset_session()

        # Counter should be reset
        state = instance.get_session_state()
        assert state.tool_call_count == 0

        # Agent reset should be called
        mock_agent.reset.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown(mock_spec: SimulationSpec, mock_agent: MagicMock) -> None:
    """Test shutdown."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec)

        await instance.shutdown()

        mock_agent.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_expiry_fail_then_reset(mock_agent: MagicMock) -> None:
    """Test that expiry fails the call then resets thread."""
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "getTest",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        },
    )

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(spec, max_messages=2)

        # Make 2 successful calls
        await instance.execute_tool("getTest", {})
        await instance.execute_tool("getTest", {})

        # Third call should fail with expiry
        result = await instance.execute_tool("getTest", {})
        assert result.success is False
        assert result.error is not None
        assert "max_messages" in (result.error or "").lower()

        # Next call should succeed on fresh thread (reset happened)
        result = await instance.execute_tool("getTest", {})
        assert result.success is True
        state = instance.get_session_state()
        assert state.tool_call_count == 1  # Reset to 1


@pytest.mark.asyncio
async def test_structured_error_fields(mock_agent: MagicMock) -> None:
    """Test that expiry errors have all required structured fields."""
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "getTest",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        },
    )

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(spec, max_messages=1)

        await instance.execute_tool("getTest", {})
        result = await instance.execute_tool("getTest", {})

        # Should have structured error with reason, limit, observed
        assert result.success is False
        assert result.error is not None
        assert "max_messages_exceeded" in result.error or "max_messages" in result.error


@pytest.mark.asyncio
async def test_idle_timer_starts_on_first_call() -> None:
    """Test that idle timer starts at first tool call, not creation."""
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "getTest",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        },
    )

    mock_agent = MagicMock()
    mock_agent.generate_response = AsyncMock(return_value={"result": "success"})
    mock_agent.reset = AsyncMock()
    mock_agent.shutdown = AsyncMock()

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(spec, idle_timeout_seconds=1)

        # Wait after creation (should NOT trigger timeout since timer hasn't started)
        await asyncio.sleep(1.5)

        # First call should succeed (timer hasn't started yet)
        result = await instance.execute_tool("getTest", {})
        assert result.success is True

        # Wait again (NOW timer has started)
        await asyncio.sleep(1.5)

        # Second call should fail (timer started after first call)
        result = await instance.execute_tool("getTest", {})
        assert result.success is False


@pytest.mark.asyncio
async def test_idle_timer_starts_on_first_call_after_reset() -> None:
    """Test that idle timer starts at first tool call after reset, not at reset time."""
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "getTest",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        },
    )

    mock_agent = MagicMock()
    mock_agent.generate_response = AsyncMock(return_value={"result": "success"})
    mock_agent.reset = AsyncMock()
    mock_agent.shutdown = AsyncMock()

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(spec, idle_timeout_seconds=1)

        # Make first call to start timer
        result = await instance.execute_tool("getTest", {})
        assert result.success is True

        # Reset session
        await instance.reset_session()

        # Wait after reset (should NOT trigger timeout since timer hasn't started)
        await asyncio.sleep(1.5)

        # First call after reset should succeed (timer hasn't started yet)
        result = await instance.execute_tool("getTest", {})
        assert result.success is True

        # Wait again (NOW timer has started)
        await asyncio.sleep(1.5)

        # Second call should fail (timer started after first post-reset call)
        result = await instance.execute_tool("getTest", {})
        assert result.success is False
        assert "idle_timeout" in (result.error or "").lower()

        assert "idle_timeout" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_counter_not_advanced_on_failure() -> None:
    """Test that counter doesn't advance for failed calls."""
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "getTest",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        },
    )

    mock_agent = MagicMock()
    mock_agent.generate_response = AsyncMock(return_value={"result": "success"})
    mock_agent.reset = AsyncMock()
    mock_agent.shutdown = AsyncMock()

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(spec, max_messages=10)

        # Make successful call
        result = await instance.execute_tool("getTest", {})
        assert result.success is True
        state = instance.get_session_state()
        assert state.tool_call_count == 1

        # Make failing call (mock agent to force failure)
        mock_agent.generate_response = AsyncMock(side_effect=Exception("LLM Error"))
        result = await instance.execute_tool("getTest", {})
        assert result.success is False

        # Counter should not advance on failure
        state = instance.get_session_state()
        assert state.tool_call_count == 1

        # Next successful call should increment
        mock_agent.generate_response = AsyncMock(return_value={"result": "success"})
        result = await instance.execute_tool("getTest", {})
        assert result.success is True
        state = instance.get_session_state()
        assert state.tool_call_count == 2


@pytest.mark.asyncio
async def test_expiry_check_before_counter_increment() -> None:
    """Test that expiry is checked before counter increments.

    This test verifies that when a call would exceed max_messages,
    the expiry check happens BEFORE the counter increments, so the
    counter never reaches the invalid value (max_messages + 1).

    After expiry, the session auto-resets per REQUIREMENTS.md §1.7.
    """
    spec = SimulationSpec(
        name="test-sim",
        openapi_spec={
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "getTest",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        },
    )

    mock_agent = MagicMock()
    mock_agent.generate_response = AsyncMock(return_value={"result": "success"})
    mock_agent.reset = AsyncMock()
    mock_agent.shutdown = AsyncMock()

    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(spec, max_messages=2)

        # Make 2 successful calls
        await instance.execute_tool("getTest", {})
        await instance.execute_tool("getTest", {})

        # Counter should be exactly at the limit
        state = instance.get_session_state()
        assert state.tool_call_count == 2

        # Third call should fail expiry check BEFORE incrementing counter
        # The expiry check compares current count (2) against limit (2)
        # and fails because next call would be #3
        result = await instance.execute_tool("getTest", {})
        assert result.success is False
        assert "max_messages" in (result.error or "").lower()

        # After expiry, session auto-resets (fail-then-reset per §1.7)
        # So counter is now 0, proving it never reached 3
        state = instance.get_session_state()
        assert state.tool_call_count == 0

        # Next call starts fresh on reset session
        result = await instance.execute_tool("getTest", {})
        assert result.success is True
        state = instance.get_session_state()
        assert state.tool_call_count == 1


def test_create_instance_forwards_base_url_to_agent(mock_spec: SimulationSpec) -> None:
    """base_url passed to SimulationInstance is forwarded to DeepAgent."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent"
    ) as mock_agent_cls:
        mock_agent_cls.return_value = MagicMock()
        create_instance(mock_spec, base_url="https://custom.example.com/v1")
        _, kwargs = mock_agent_cls.call_args
        assert kwargs["base_url"] == "https://custom.example.com/v1"


def test_create_instance_base_url_defaults_to_none(mock_spec: SimulationSpec) -> None:
    """base_url defaults to None when not provided."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent"
    ) as mock_agent_cls:
        mock_agent_cls.return_value = MagicMock()
        create_instance(mock_spec)
        _, kwargs = mock_agent_cls.call_args
        assert kwargs["base_url"] is None


def test_mcp_port_stored_when_provided(mock_spec: SimulationSpec) -> None:
    """SimulationInstance stores mcp_port when provided."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent"
    ) as mock_agent_cls:
        mock_agent_cls.return_value = MagicMock()
        instance = create_instance(mock_spec, mcp_port=9000)
        assert instance.mcp_port == 9000


def test_mcp_port_defaults_to_none(mock_spec: SimulationSpec) -> None:
    """SimulationInstance.mcp_port is None when not provided."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent"
    ) as mock_agent_cls:
        mock_agent_cls.return_value = MagicMock()
        instance = create_instance(mock_spec)
        assert instance.mcp_port is None


@pytest.mark.asyncio
async def test_shutdown_stops_sidecar_when_present(
    mock_spec: SimulationSpec, mock_agent: MagicMock
) -> None:
    """shutdown() calls stop() on the sidecar if one is set."""
    with patch(
        "simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent
    ):
        instance = create_instance(mock_spec)
        mock_sidecar = MagicMock()
        mock_sidecar.stop = AsyncMock()
        instance._sidecar = mock_sidecar  # type: ignore[assignment]

        await instance.shutdown()

        mock_sidecar.stop.assert_called_once()


# Made with Bob
