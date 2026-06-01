"""Structured logging utilities for simulation harness."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from simulation_harness.models.domain import SessionState

# Get logger for this module
logger = logging.getLogger(__name__)

# Outcome taxonomy per REQUIREMENTS.md §2.4
OutcomeType = Literal[
    "success",
    "max_messages_exceeded",
    "idle_timeout_exceeded",
    "concurrent_queue_full",
    "llm_provider_error",
    "tool_invocation_error",
    "internal_error",
]


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for the given name.

    Args:
        name: Logger name (typically __name__ of the calling module)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def log_tool_call(
    tool_name: str,
    outcome: OutcomeType,
    duration_ms: int,
    tool_call_count: int,
    queue_depth_at_admission: int,
    token_usage: Optional[Dict[str, int]],
    transport: Literal["sse", "streamable_http"],
) -> Dict[str, Any]:
    """
    Log a tool call with all required fields per REQUIREMENTS.md §2.4.

    Args:
        tool_name: Name of the tool that was called
        outcome: Outcome taxonomy value
        duration_ms: Duration in milliseconds
        tool_call_count: Current tool call count
        queue_depth_at_admission: Queue depth when admitted
        token_usage: Token usage dict or None
        transport: Transport type used

    Returns:
        Dict containing the log entry for testing
    """
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_name": tool_name,
        "outcome": outcome,
        "duration_ms": duration_ms,
        "tool_call_count": tool_call_count,
        "queue_depth_at_admission": queue_depth_at_admission,
        "token_usage": token_usage,
        "transport": transport,
    }

    logger.info(json.dumps(log_entry))
    return log_entry


def log_tool_call_legacy(
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    duration_ms: int,
    session_state: SessionState,
    success: bool,
    error: Optional[str] = None,
) -> None:
    """
    Legacy log_tool_call function for backward compatibility.

    DEPRECATED: Use log_tool_call with new signature instead.

    Args:
        tool_name: Name of the tool that was called
        arguments: Arguments passed to the tool
        result: Result returned by the tool
        duration_ms: Duration of the tool call in milliseconds
        session_state: Current session state
        success: Whether the tool call succeeded
        error: Error message if the tool call failed
    """
    log_data = {
        "tool_name": tool_name,
        "arguments": arguments,
        "result": result,
        "duration_ms": duration_ms,
        "success": success,
        "session_state": {
            "tool_call_count": session_state.tool_call_count,
            "max_messages": session_state.max_messages,
            "idle_timeout_seconds": session_state.idle_timeout_seconds,
            "last_activity": session_state.last_activity.isoformat(),
            "queue_depth": session_state.queue_depth,
            "max_queue_depth": session_state.max_queue_depth,
        },
    }

    if error:
        log_data["error"] = error

    # Log at appropriate level based on success
    if success:
        logger.info(
            f"Tool call: {tool_name} completed in {duration_ms}ms "
            f"(count: {session_state.tool_call_count}/{session_state.max_messages}, "
            f"queue: {session_state.queue_depth}/{session_state.max_queue_depth})",
            extra={"structured_data": log_data},
        )
    else:
        logger.error(
            f"Tool call: {tool_name} failed in {duration_ms}ms - {error or 'Unknown error'} "
            f"(count: {session_state.tool_call_count}/{session_state.max_messages}, "
            f"queue: {session_state.queue_depth}/{session_state.max_queue_depth})",
            extra={"structured_data": log_data},
        )


# Made with Bob
