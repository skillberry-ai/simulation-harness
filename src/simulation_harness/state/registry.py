"""Registry for per-thread SimulationStore instances."""

import logging
from pathlib import Path

from .loader import load_store_from_skill
from .store import SimulationStore

logger = logging.getLogger(__name__)


class StoreRegistry:
    """Registry managing per-thread SimulationStore instances.

    Each thread gets its own isolated store instance, lazily created on first access.
    Stores can be reset to seed state or dropped to free memory.
    """

    def __init__(self, skill_dir: Path) -> None:
        """Initialize the registry.

        Args:
            skill_dir: Path to the skill directory containing schema.json and db.json
        """
        self.skill_dir = skill_dir
        self._stores: dict[str, SimulationStore] = {}
        logger.debug(f"StoreRegistry initialized for skill: {skill_dir}")

    def for_thread(self, thread_id: str) -> SimulationStore:
        """Get or create the store for a thread.

        Args:
            thread_id: The thread identifier

        Returns:
            SimulationStore instance for this thread
        """
        if thread_id not in self._stores:
            logger.info(f"Creating new store for thread: {thread_id}")
            self._stores[thread_id] = load_store_from_skill(self.skill_dir)

        return self._stores[thread_id]

    def reset(self, thread_id: str) -> None:
        """Reset a thread's store to seed state.

        Args:
            thread_id: The thread identifier
        """
        if thread_id in self._stores:
            logger.info(f"Resetting store for thread: {thread_id}")
            self._stores[thread_id].reset()
        else:
            logger.warning(
                f"Attempted to reset non-existent store for thread: {thread_id}"
            )

    def drop(self, thread_id: str) -> None:
        """Drop a thread's store to free memory.

        Args:
            thread_id: The thread identifier
        """
        if thread_id in self._stores:
            logger.info(f"Dropping store for thread: {thread_id}")
            del self._stores[thread_id]
        else:
            logger.debug(
                f"Attempted to drop non-existent store for thread: {thread_id}"
            )

    def drop_all(self) -> None:
        """Drop all stores to free memory."""
        count = len(self._stores)
        logger.info(f"Dropping all {count} stores")
        self._stores.clear()

    def thread_count(self) -> int:
        """Get the number of active thread stores.

        Returns:
            Count of stores currently in memory
        """
        return len(self._stores)


# Made with Bob
