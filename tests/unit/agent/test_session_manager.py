"""Tests for SessionManager."""

import asyncio
import pytest
from langgraph.checkpoint.memory import MemorySaver
from simulation_harness.agent.session_manager import SessionManager


@pytest.fixture
def memory_saver():
    """Create a MemorySaver instance."""
    return MemorySaver()


@pytest.fixture
def session_manager(memory_saver):
    """Create a SessionManager instance."""
    return SessionManager(
        checkpointer=memory_saver,
        timeout_seconds=60,
        max_sessions=10,
        cleanup_interval_seconds=1,
    )


def test_session_manager_initialization(memory_saver):
    """Test SessionManager initializes correctly."""
    manager = SessionManager(
        checkpointer=memory_saver,
        timeout_seconds=60,
        max_sessions=10,
    )

    assert manager.checkpointer is memory_saver
    assert manager.timeout_seconds == 60
    assert manager.max_sessions == 10
    assert manager.cleanup_interval == 60  # default
    assert len(manager.last_activity) == 0
    assert manager._running is False


def test_session_manager_initialization_without_checkpointer():
    """Test SessionManager initializes without checkpointer."""
    manager = SessionManager(
        checkpointer=None,
        timeout_seconds=60,
        max_sessions=10,
    )

    assert manager.checkpointer is None
    assert manager.timeout_seconds == 60
    assert manager.max_sessions == 10


def test_record_activity(session_manager):
    """Test recording session activity."""
    session_manager.record_activity("thread1")

    assert "thread1" in session_manager.last_activity
    assert session_manager.get_active_session_count() == 1


def test_get_active_session_count(session_manager):
    """Test getting active session count."""
    assert session_manager.get_active_session_count() == 0

    session_manager.record_activity("thread1")
    session_manager.record_activity("thread2")

    assert session_manager.get_active_session_count() == 2


def test_is_session_expired(session_manager):
    """Test checking if session is expired."""
    import time

    # Record activity
    session_manager.record_activity("thread1")

    # Should not be expired immediately
    assert not session_manager.is_session_expired("thread1")

    # Manually set old timestamp
    session_manager.last_activity["thread1"] = time.time() - 120  # 2 minutes ago

    # Should be expired now (timeout is 60 seconds)
    assert session_manager.is_session_expired("thread1")

    # Non-existent session should not be expired
    assert not session_manager.is_session_expired("nonexistent")


@pytest.mark.asyncio
async def test_cleanup_expired_sessions(session_manager):
    """Test cleaning up expired sessions."""
    import time

    # Add some sessions
    session_manager.record_activity("thread1")
    session_manager.record_activity("thread2")

    # Make thread1 expired
    session_manager.last_activity["thread1"] = time.time() - 120

    # Cleanup
    cleaned = await session_manager.cleanup_expired_sessions()

    assert cleaned == 1
    assert "thread1" not in session_manager.last_activity
    assert "thread2" in session_manager.last_activity


@pytest.mark.asyncio
async def test_cleanup_expired_sessions_without_checkpointer():
    """Test cleanup does nothing without checkpointer."""
    manager = SessionManager(
        checkpointer=None,
        timeout_seconds=60,
        max_sessions=10,
    )

    cleaned = await manager.cleanup_expired_sessions()
    assert cleaned == 0


@pytest.mark.asyncio
async def test_enforce_max_sessions(session_manager):
    """Test enforcing maximum session limit."""

    # Add more sessions than max (max is 10)
    for i in range(12):
        session_manager.record_activity(f"thread{i}")
        # Add small delay to ensure different timestamps
        await asyncio.sleep(0.01)

    assert session_manager.get_active_session_count() == 12

    # Enforce limit
    evicted = await session_manager.enforce_max_sessions()

    assert evicted == 2
    assert session_manager.get_active_session_count() == 10


def test_clear_session(session_manager):
    """Test clearing a specific session."""
    session_manager.record_activity("thread1")
    session_manager.record_activity("thread2")

    # Clear thread1
    result = session_manager.clear_session("thread1")

    assert result is True
    assert "thread1" not in session_manager.last_activity
    assert "thread2" in session_manager.last_activity

    # Try to clear non-existent session
    result = session_manager.clear_session("nonexistent")
    assert result is False


def test_clear_all_sessions(session_manager):
    """Test clearing all sessions."""
    session_manager.record_activity("thread1")
    session_manager.record_activity("thread2")
    session_manager.record_activity("thread3")

    count = session_manager.clear_all_sessions()

    assert count == 3
    assert session_manager.get_active_session_count() == 0


@pytest.mark.asyncio
async def test_start_and_stop(session_manager):
    """Test starting and stopping cleanup task."""
    # Start
    session_manager.start()
    assert session_manager._running is True
    assert session_manager._cleanup_task is not None

    # Stop
    await session_manager.stop()
    assert session_manager._running is False
    assert session_manager._cleanup_task is None


@pytest.mark.asyncio
async def test_start_without_checkpointer():
    """Test start does nothing without checkpointer."""
    manager = SessionManager(
        checkpointer=None,
        timeout_seconds=60,
        max_sessions=10,
    )

    manager.start()
    assert manager._running is False
    assert manager._cleanup_task is None


# Made with Bob
