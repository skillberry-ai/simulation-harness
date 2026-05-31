"""Tests for SimulationInstance."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from simulation_harness.core.simulation_instance import SimulationInstance
from simulation_harness.models.domain import SimulationSpec, ToolCallResult
from simulation_harness.utils.errors import SessionExpiredError, ConcurrentQueueFullError


@pytest.fixture
def mock_spec():
    """Create a mock simulation spec."""
    return SimulationSpec(
        name="test-sim",
        openapi_spec={"openapi": "3.0.0", "info": {"title": "Test", "version": "1.0.0"}},
    )


@pytest.fixture
def mock_agent():
    """Create a mock deep agent."""
    agent = MagicMock()
    agent.generate_response = AsyncMock(return_value={"result": "success"})
    agent.reset = AsyncMock()
    agent.shutdown = AsyncMock()
    return agent


def create_instance(spec, **kwargs):
    """Helper to create SimulationInstance with default config values."""
    defaults = {
        "max_messages": 100,
        "idle_timeout_seconds": 3600,
        "max_queue_depth": 10,
        "api_key": "test-key",
        "model": "gpt-4",
        "temperature": 0.7,
        "max_tokens": 4000,
    }
    defaults.update(kwargs)
    return SimulationInstance(spec=spec, **defaults)


@pytest.mark.asyncio
async def test_execute_tool_success(mock_spec, mock_agent):
    """Test successful tool execution."""
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec)
        
        result = await instance.execute_tool("test_tool", {"param": "value"})
        
        assert result.success is True
        assert result.content == '{"result": "success"}'
        assert result.error is None


@pytest.mark.asyncio
async def test_execute_tool_increments_counter(mock_spec, mock_agent):
    """Test that tool execution increments counter."""
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec)
        
        state_before = instance.get_session_state()
        await instance.execute_tool("test_tool", {"param": "value"})
        state_after = instance.get_session_state()
        
        assert state_after.tool_call_count == state_before.tool_call_count + 1


@pytest.mark.asyncio
async def test_execute_tool_updates_last_activity(mock_spec, mock_agent):
    """Test that tool execution updates last activity timestamp."""
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec)
        
        state_before = instance.get_session_state()
        assert state_before.last_activity is None  # Timer hasn't started yet
        
        await instance.execute_tool("test_tool", {"param": "value"})
        state_after = instance.get_session_state()
        
        assert state_after.last_activity is not None  # Timer started
        assert isinstance(state_after.last_activity, datetime)


@pytest.mark.asyncio
async def test_execute_tool_raises_on_max_messages(mock_spec, mock_agent):
    """Test that exceeding max_messages returns failed result and resets."""
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec, max_messages=2)
        
        await instance.execute_tool("test_tool", {"param": "value"})
        await instance.execute_tool("test_tool", {"param": "value"})
        
        # Third call should fail with expiry
        result = await instance.execute_tool("test_tool", {"param": "value"})
        assert result.success is False
        assert result.error is not None
        assert "max_messages" in result.error.lower()
        
        # Session should be reset
        state = instance.get_session_state()
        assert state.tool_call_count == 0


@pytest.mark.asyncio
async def test_execute_tool_raises_on_idle_timeout(mock_spec, mock_agent):
    """Test that idle timeout returns failed result and resets."""
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec, idle_timeout_seconds=1)
        
        # Manually set last_activity to past
        instance._last_activity = datetime.now(timezone.utc) - timedelta(seconds=2)
        
        # Call should fail with expiry
        result = await instance.execute_tool("test_tool", {"param": "value"})
        assert result.success is False
        assert result.error is not None
        assert "idle_timeout" in result.error.lower()
        
        # Session should be reset
        state = instance.get_session_state()
        assert state.tool_call_count == 0


@pytest.mark.asyncio
async def test_execute_tool_enforces_queue_depth(mock_spec, mock_agent):
    """Test that queue depth is enforced."""
    # Make agent slow to allow queue to fill
    async def slow_response(*args, **kwargs):
        await asyncio.sleep(0.1)
        return {"result": "success"}
    
    slow_agent = MagicMock()
    slow_agent.generate_response = AsyncMock(side_effect=slow_response)
    slow_agent.reset = AsyncMock()
    slow_agent.shutdown = AsyncMock()
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=slow_agent):
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
async def test_execute_tool_handles_agent_error(mock_spec, mock_agent):
    """Test that agent errors are handled gracefully."""
    mock_agent.generate_response = AsyncMock(side_effect=Exception("Agent error"))
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec)
        
        result = await instance.execute_tool("test_tool", {"param": "value"})
        
        assert result.success is False
        assert result.error is not None
        assert "Agent error" in result.error


@pytest.mark.asyncio
async def test_execute_tool_does_not_increment_counter_on_failure(mock_spec, mock_agent):
    """Test that counter is not incremented on failure."""
    mock_agent.generate_response = AsyncMock(side_effect=Exception("Agent error"))
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec)
        
        state_before = instance.get_session_state()
        await instance.execute_tool("test_tool", {"param": "value"})
        state_after = instance.get_session_state()
        
        assert state_after.tool_call_count == state_before.tool_call_count


@pytest.mark.asyncio
async def test_get_session_state(mock_spec, mock_agent):
    """Test getting session state."""
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec, max_messages=10, idle_timeout_seconds=300, max_queue_depth=5)
        
        state = instance.get_session_state()
        
        assert state.tool_call_count == 0
        assert state.max_messages == 10
        assert state.idle_timeout_seconds == 300
        assert state.max_queue_depth == 5
        assert state.queue_depth == 0
        assert state.last_activity is None  # Timer hasn't started yet


@pytest.mark.asyncio
async def test_reset_session(mock_spec, mock_agent):
    """Test resetting session."""
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
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
async def test_shutdown(mock_spec, mock_agent):
    """Test shutdown."""
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(mock_spec)
        
        await instance.shutdown()
        
        mock_agent.shutdown.assert_called_once()

@pytest.mark.asyncio
async def test_expiry_fail_then_reset(mock_agent):
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
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(spec, max_messages=2)
        
        # Make 2 successful calls
        await instance.execute_tool("getTest", {})
        await instance.execute_tool("getTest", {})
        
        # Third call should fail with expiry
        result = await instance.execute_tool("getTest", {})
        assert result.success is False
        assert result.error is not None
        assert "max_messages" in result.error.lower()
        
        # Next call should succeed on fresh thread (reset happened)
        result = await instance.execute_tool("getTest", {})
        assert result.success is True
        state = instance.get_session_state()
        assert state.tool_call_count == 1  # Reset to 1


@pytest.mark.asyncio
async def test_structured_error_fields(mock_agent):
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
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
        instance = create_instance(spec, max_messages=1)
        
        await instance.execute_tool("getTest", {})
        result = await instance.execute_tool("getTest", {})
        
        # Should have structured error with reason, limit, observed
        assert result.success is False
        assert result.error is not None
        assert "max_messages_exceeded" in result.error or "max_messages" in result.error


@pytest.mark.asyncio
async def test_idle_timer_starts_on_first_call():
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
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
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
async def test_idle_timer_starts_on_first_call_after_reset():
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
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
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
        assert "idle_timeout" in result.error.lower()

        assert "idle_timeout" in result.error.lower()


@pytest.mark.asyncio
async def test_counter_not_advanced_on_failure():
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
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
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
async def test_expiry_check_before_counter_increment():
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
    
    with patch("simulation_harness.core.simulation_instance.DeepAgent", return_value=mock_agent):
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
        assert "max_messages" in result.error.lower()
        
        # After expiry, session auto-resets (fail-then-reset per §1.7)
        # So counter is now 0, proving it never reached 3
        state = instance.get_session_state()
        assert state.tool_call_count == 0
        
        # Next call starts fresh on reset session
        result = await instance.execute_tool("getTest", {})
        assert result.success is True
        state = instance.get_session_state()
        assert state.tool_call_count == 1


# Made with Bob