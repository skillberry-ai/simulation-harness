"""Session management for Deep Agent context persistence.

This module provides session cleanup and management for in-memory checkpointers.
"""

import asyncio
import contextlib
import time
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


class SessionManager:
    """Manages session cleanup for in-memory checkpointers.

    Automatically removes expired sessions based on inactivity timeout.
    Only works with MemorySaver checkpointers.
    """

    def __init__(
        self,
        checkpointer: MemorySaver | None,
        timeout_seconds: int,
        max_sessions: int,
        cleanup_interval_seconds: int = 60,
    ):
        """Initialize SessionManager.

        Args:
            checkpointer: MemorySaver instance to manage (None if disabled)
            timeout_seconds: Session inactivity timeout in seconds
            max_sessions: Maximum number of concurrent sessions
            cleanup_interval_seconds: How often to run cleanup (default: 60s)
        """
        self.checkpointer = checkpointer
        self.timeout_seconds = timeout_seconds
        self.max_sessions = max_sessions
        self.cleanup_interval = cleanup_interval_seconds

        # Track last activity time for each thread_id
        self.last_activity: dict[str, float] = {}

        # Cleanup task
        self._cleanup_task: asyncio.Task[Any] | None = None
        self._running = False

        if self.checkpointer:
            logger.info(
                f"Session cleanup manager initialized: timeout={timeout_seconds}s, "
                f"max_sessions={max_sessions}, cleanup_interval={cleanup_interval_seconds}s"
            )

    def record_activity(self, thread_id: str) -> None:
        """Record activity for a thread/session.

        Args:
            thread_id: Thread identifier
        """
        self.last_activity[thread_id] = time.time()

    def get_active_session_count(self) -> int:
        """Get count of active sessions.

        Returns:
            Number of active sessions
        """
        return len(self.last_activity)

    def is_session_expired(self, thread_id: str) -> bool:
        """Check if a session has expired.

        Args:
            thread_id: Thread identifier

        Returns:
            True if session is expired, False otherwise
        """
        if thread_id not in self.last_activity:
            return False

        last_time = self.last_activity[thread_id]
        return (time.time() - last_time) > self.timeout_seconds

    async def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions from checkpointer.

        Returns:
            Number of sessions cleaned up
        """
        if not self.checkpointer or not isinstance(self.checkpointer, MemorySaver):
            return 0

        now = time.time()
        expired_threads = [
            thread_id
            for thread_id, last_time in self.last_activity.items()
            if (now - last_time) > self.timeout_seconds
        ]

        if not expired_threads:
            return 0

        # Clean up expired sessions
        cleaned_count = 0
        for thread_id in expired_threads:
            try:
                # Remove from activity tracking
                del self.last_activity[thread_id]

                # Clear checkpointer state for this thread
                # Note: MemorySaver stores data in internal dict
                # We need to access the storage dict to clear it
                if hasattr(self.checkpointer, "storage"):
                    # Remove all checkpoints for this thread
                    keys_to_remove = [
                        key
                        for key in self.checkpointer.storage
                        if key[0] == thread_id  # thread_id is first element of tuple key
                    ]
                    for key in keys_to_remove:
                        del self.checkpointer.storage[key]

                cleaned_count += 1

                logger.debug(
                    f"Cleaned up expired session: thread_id={thread_id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to cleanup session: thread_id={thread_id}, error={str(e)}"
                )

        if cleaned_count > 0:
            logger.info(
                f"Session cleanup completed: cleaned={cleaned_count}, "
                f"active_sessions={len(self.last_activity)}"
            )

        return cleaned_count

    async def enforce_max_sessions(self) -> int:
        """Enforce maximum session limit using LRU eviction.

        Returns:
            Number of sessions evicted
        """
        if not self.checkpointer:
            return 0

        current_count = len(self.last_activity)
        if current_count <= self.max_sessions:
            return 0

        # Sort by last activity time (oldest first)
        sorted_sessions = sorted(self.last_activity.items(), key=lambda x: x[1])

        # Calculate how many to evict
        evict_count = current_count - self.max_sessions
        sessions_to_evict = sorted_sessions[:evict_count]

        evicted = 0
        for thread_id, _ in sessions_to_evict:
            try:
                del self.last_activity[thread_id]

                # Clear from checkpointer
                if hasattr(self.checkpointer, "storage"):
                    keys_to_remove = [
                        key for key in self.checkpointer.storage if key[0] == thread_id
                    ]
                    for key in keys_to_remove:
                        del self.checkpointer.storage[key]

                evicted += 1

                logger.debug(
                    f"Evicted session due to max limit: thread_id={thread_id}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to evict session: thread_id={thread_id}, error={str(e)}"
                )

        if evicted > 0:
            logger.warning(
                f"Max sessions limit enforced: evicted={evicted}, "
                f"max_sessions={self.max_sessions}, active_sessions={len(self.last_activity)}"
            )

        return evicted

    async def _cleanup_loop(self) -> None:
        """Background task that periodically cleans up expired sessions."""
        logger.info("Session cleanup loop started")

        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)

                # Run cleanup
                cleaned = await self.cleanup_expired_sessions()
                evicted = await self.enforce_max_sessions()

                if cleaned > 0 or evicted > 0:
                    logger.info(
                        f"Periodic cleanup completed: expired_cleaned={cleaned}, "
                        f"lru_evicted={evicted}, active_sessions={len(self.last_activity)}"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"Error in cleanup loop: {str(e)}",
                    exc_info=True,
                )

        logger.info("Session cleanup loop stopped")

    def start(self) -> None:
        """Start the background cleanup task."""
        if not self.checkpointer:
            logger.debug("Checkpointer disabled, cleanup not started")
            return

        if self._running:
            logger.warning("Cleanup task already running")
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session cleanup task started")

    async def stop(self) -> None:
        """Stop the background cleanup task."""
        if not self._running:
            return

        self._running = False

        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

        logger.info("Session cleanup task stopped")

    def clear_session(self, thread_id: str) -> bool:
        """Manually clear a specific session.

        Args:
            thread_id: Thread identifier to clear

        Returns:
            True if session was cleared, False if not found
        """
        if thread_id not in self.last_activity:
            return False

        try:
            del self.last_activity[thread_id]

            # Clear from checkpointer
            if self.checkpointer and hasattr(self.checkpointer, "storage"):
                keys_to_remove = [key for key in self.checkpointer.storage if key[0] == thread_id]
                for key in keys_to_remove:
                    del self.checkpointer.storage[key]

            logger.info(f"Session cleared manually: thread_id={thread_id}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to clear session: thread_id={thread_id}, error={str(e)}"
            )
            return False

    def clear_all_sessions(self) -> int:
        """Clear all sessions.

        Returns:
            Number of sessions cleared
        """
        count = len(self.last_activity)

        self.last_activity.clear()

        # Clear checkpointer storage
        if self.checkpointer and hasattr(self.checkpointer, "storage"):
            self.checkpointer.storage.clear()

        logger.info(f"All sessions cleared: count={count}")
        return count

# Made with Bob
