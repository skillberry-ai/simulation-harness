"""State management for simulation sessions.

This package provides in-memory state storage for simulation sessions,
with schema validation and tool-backed access patterns.
"""

from .errors import (
    StoreError,
    NotFoundError,
    DuplicateKeyError,
    ValidationError,
    UnknownStoreError,
    BadQueryError,
)
from .store import SimulationStore
from .loader import load_store_from_skill
from .registry import StoreRegistry
from .tools import create_state_tools

__all__ = [
    "StoreError",
    "NotFoundError",
    "DuplicateKeyError",
    "ValidationError",
    "UnknownStoreError",
    "BadQueryError",
    "SimulationStore",
    "load_store_from_skill",
    "StoreRegistry",
    "create_state_tools",
]

# Made with Bob
