"""LangChain tools for state store access.

These tools expose the SimulationStore to the LLM via structured tool calls.
Each tool resolves the per-thread store from a registry passed via RunnableConfig.
"""

from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, StructuredTool
from pydantic import BaseModel, Field

from .errors import (
    NotFoundError,
    DuplicateKeyError,
    ValidationError,
    UnknownStoreError,
    BadQueryError,
)


# Pydantic models for tool arguments

class StateGetArgs(BaseModel):
    """Arguments for state_get tool."""
    store: str = Field(..., description="The store name (e.g., 'restaurants', 'reservations')")
    id: str = Field(..., description="The primary key value to retrieve")


class StateListArgs(BaseModel):
    """Arguments for state_list tool."""
    store: str = Field(..., description="The store name")
    where: dict | None = Field(None, description="Optional filter predicates (see where DSL)")
    sort: list[list[str]] | None = Field(None, description="Optional sort specification as [[field, 'asc'|'desc'], ...]")
    limit: int | None = Field(None, description="Optional maximum number of results")


class StateCountArgs(BaseModel):
    """Arguments for state_count tool."""
    store: str = Field(..., description="The store name")
    where: dict | None = Field(None, description="Optional filter predicates")


class StateInsertArgs(BaseModel):
    """Arguments for state_insert tool."""
    store: str = Field(..., description="The store name")
    entity: dict = Field(..., description="The entity to insert (must include primary key)")


class StateUpdateArgs(BaseModel):
    """Arguments for state_update tool."""
    store: str = Field(..., description="The store name")
    id: str = Field(..., description="The primary key value")
    patch: dict = Field(..., description="Fields to update (merged with existing entity)")


class StateDeleteArgs(BaseModel):
    """Arguments for state_delete tool."""
    store: str = Field(..., description="The store name")
    id: str = Field(..., description="The primary key value to delete")


# Tool implementation functions

def _get_store_from_config(config: RunnableConfig) -> Any:
    """Extract the SimulationStore for the current thread from config.
    
    Args:
        config: RunnableConfig containing store_registry and thread_id
        
    Returns:
        SimulationStore instance for this thread
        
    Raises:
        KeyError: If config is missing required keys
    """
    registry = config["configurable"]["store_registry"]
    thread_id = config["configurable"]["thread_id"]
    return registry.for_thread(thread_id)


def _error_to_dict(error: Exception) -> dict:
    """Convert a store error to a JSON-serializable error dict.
    
    Args:
        error: The exception to convert
        
    Returns:
        Dictionary with error code and message
    """
    if isinstance(error, NotFoundError):
        return {"error": "not_found", "message": str(error)}
    elif isinstance(error, DuplicateKeyError):
        return {"error": "duplicate_key", "message": str(error)}
    elif isinstance(error, ValidationError):
        return {
            "error": "validation_error",
            "message": str(error),
            "field_path": getattr(error, "field_path", None)
        }
    elif isinstance(error, UnknownStoreError):
        return {
            "error": "unknown_store",
            "message": str(error),
            "available_stores": getattr(error, "available_stores", [])
        }
    elif isinstance(error, BadQueryError):
        return {"error": "bad_query", "message": str(error)}
    else:
        return {"error": "internal_error", "message": str(error)}


def state_get(
    store: str,
    id: str,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> dict:
    """Get an entity by its primary key.
    
    Args:
        store: The store name
        id: The primary key value
        config: Injected RunnableConfig (not visible to LLM)
        
    Returns:
        The entity dict, or an error dict if not found
    """
    try:
        sim_store = _get_store_from_config(config)
        entity = sim_store.get(store, id)
        
        if entity is None:
            return {"error": "not_found", "message": f"Entity with id '{id}' not found in store '{store}'"}
        
        return entity
    
    except Exception as e:
        return _error_to_dict(e)


def state_list(
    store: str,
    where: dict | None = None,
    sort: list[list[str]] | None = None,
    limit: int | None = None,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> list[dict] | dict:
    """List entities from a store with optional filtering and sorting.
    
    Args:
        store: The store name
        where: Optional filter predicates
        sort: Optional sort specification as list of [field, direction] pairs
        limit: Optional result limit
        config: Injected RunnableConfig (not visible to LLM)
        
    Returns:
        List of entities, or an error dict
    """
    try:
        sim_store = _get_store_from_config(config)
        
        # Validate and convert sort parameter
        sort_tuples = None
        if sort:
            # Validate sort format before conversion
            for item in sort:
                if not isinstance(item, list) or len(item) != 2:
                    return {
                        "error": "bad_query",
                        "message": f"Sort items must be [field, direction] pairs, got: {item}"
                    }
            # Convert list of lists to list of tuples for internal API
            sort_tuples = [(field, direction) for field, direction in sort]
        
        return sim_store.list(store, where=where, sort=sort_tuples, limit=limit)
    
    except Exception as e:
        return _error_to_dict(e)


def state_count(
    store: str,
    where: dict | None = None,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> int | dict:
    """Count entities in a store with optional filtering.
    
    Args:
        store: The store name
        where: Optional filter predicates
        config: Injected RunnableConfig (not visible to LLM)
        
    Returns:
        Count of matching entities, or an error dict
    """
    try:
        sim_store = _get_store_from_config(config)
        return sim_store.count(store, where=where)
    
    except Exception as e:
        return _error_to_dict(e)


def state_insert(
    store: str,
    entity: dict,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> dict:
    """Insert a new entity into a store.
    
    Args:
        store: The store name
        entity: The entity to insert (must include primary key)
        config: Injected RunnableConfig (not visible to LLM)
        
    Returns:
        The inserted entity (echoed), or an error dict
    """
    try:
        sim_store = _get_store_from_config(config)
        return sim_store.insert(store, entity)
    
    except Exception as e:
        return _error_to_dict(e)


def state_update(
    store: str,
    id: str,
    patch: dict,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> dict:
    """Update an existing entity by merging a patch.
    
    Args:
        store: The store name
        id: The primary key value
        patch: Fields to update
        config: Injected RunnableConfig (not visible to LLM)
        
    Returns:
        The updated entity, or an error dict
    """
    try:
        sim_store = _get_store_from_config(config)
        return sim_store.update(store, id, patch)
    
    except Exception as e:
        return _error_to_dict(e)


def state_delete(
    store: str,
    id: str,
    *,
    config: Annotated[RunnableConfig, InjectedToolArg]
) -> dict:
    """Delete an entity by its primary key.
    
    Args:
        store: The store name
        id: The primary key value
        config: Injected RunnableConfig (not visible to LLM)
        
    Returns:
        The deleted entity, or an error dict
    """
    try:
        sim_store = _get_store_from_config(config)
        return sim_store.delete(store, id)
    
    except Exception as e:
        return _error_to_dict(e)


# Create StructuredTool instances

def create_state_tools() -> list[StructuredTool]:
    """Create the six state management tools.
    
    Returns:
        List of StructuredTool instances ready to bind to an LLM
    """
    return [
        StructuredTool(
            name="state_get",
            description="Get an entity by its primary key from a store",
            func=state_get,
            args_schema=StateGetArgs
        ),
        StructuredTool(
            name="state_list",
            description="List entities from a store with optional filtering, sorting, and limiting",
            func=state_list,
            args_schema=StateListArgs
        ),
        StructuredTool(
            name="state_count",
            description="Count entities in a store with optional filtering",
            func=state_count,
            args_schema=StateCountArgs
        ),
        StructuredTool(
            name="state_insert",
            description="Insert a new entity into a store (must include primary key)",
            func=state_insert,
            args_schema=StateInsertArgs
        ),
        StructuredTool(
            name="state_update",
            description="Update an existing entity by merging a patch",
            func=state_update,
            args_schema=StateUpdateArgs
        ),
        StructuredTool(
            name="state_delete",
            description="Delete an entity by its primary key",
            func=state_delete,
            args_schema=StateDeleteArgs
        ),
    ]

# Made with Bob
