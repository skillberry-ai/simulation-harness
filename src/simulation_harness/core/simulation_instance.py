"""SimulationInstance - wraps Deep Agent with session management."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from simulation_harness.agent.deep_agent import DeepAgent
from simulation_harness.models.domain import SimulationSpec, SessionState, ToolCallResult
from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.utils.errors import SessionExpiredError, ConcurrentQueueFullError
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


class SimulationInstance:
    """Simulation instance with session management and bounded queue."""

    def __init__(
        self,
        spec: SimulationSpec,
        max_messages: int,
        idle_timeout_seconds: int,
        max_queue_depth: int,
        api_key: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> None:
        """Initialize simulation instance.

        Args:
            spec: Simulation specification
            max_messages: Maximum number of tool calls before session expires
            idle_timeout_seconds: Idle timeout in seconds
            max_queue_depth: Maximum concurrent queue depth
            api_key: LLM API key
            model: Model name
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate
        """
        self.spec = spec
        self._max_messages = max_messages
        self._idle_timeout_seconds = idle_timeout_seconds
        self._max_queue_depth = max_queue_depth
        
        # Creation timestamp
        self.created_at = datetime.now(timezone.utc)

        # Session state
        self._tool_call_count = 0
        self._last_activity = None  # Timer starts on first call
        self._queue_lock = asyncio.Lock()
        self._current_queue_depth = 0

        # Parse OpenAPI spec and create agent
        parsed_spec = OpenAPISpec(spec.openapi_spec)
        operations = parsed_spec.operations

        self._agent = DeepAgent(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=None,
            spec=parsed_spec,
            operations=operations,
            session_timeout_seconds=idle_timeout_seconds,
        )

        logger.info(
            f"SimulationInstance created: name={spec.name}, "
            f"max_messages={max_messages}, idle_timeout={idle_timeout_seconds}s, "
            f"max_queue_depth={max_queue_depth}"
        )

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
        """Execute a tool call with expiry checking and auto-reset.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            Tool call result

        Raises:
            ConcurrentQueueFullError: If queue is full
        """
        # Check queue depth
        async with self._queue_lock:
            if self._current_queue_depth >= self._max_queue_depth:
                raise ConcurrentQueueFullError(
                    f"Queue is full (depth={self._current_queue_depth}, max={self._max_queue_depth})"
                )
            self._current_queue_depth += 1

        try:
            # Start idle timer on first call
            if self._last_activity is None:
                self._last_activity = datetime.now(timezone.utc)
            
            # Check session expiry BEFORE execution
            try:
                self._check_session_expiry()
            except SessionExpiredError as e:
                # Log the expiry
                logger.warning(f"Session expired: {e.reason} (limit={e.limit}, observed={e.observed})")
                
                # Reset session for next call
                await self.reset_session()
                
                # Return error for THIS call
                return ToolCallResult(
                    success=False,
                    content="",
                    error=f"Session expired: {e.reason} (limit={e.limit}, observed={e.observed})",
                )

            # Execute tool normally
            try:
                response = await self._agent.generate_response(tool_name, arguments)
                content = json.dumps(response)

                # Update session state on success
                self._tool_call_count += 1
                self._last_activity = datetime.now(timezone.utc)

                logger.debug(
                    f"Tool executed successfully: tool={tool_name}, "
                    f"count={self._tool_call_count}"
                )

                return ToolCallResult(
                    success=True,
                    content=content,
                    error=None,
                )

            except Exception as e:
                # Don't increment counter on failure
                logger.error(f"Tool execution failed: tool={tool_name}, error={str(e)}")
                return ToolCallResult(
                    success=False,
                    content="",
                    error=str(e),
                )

        finally:
            # Always decrement queue depth
            async with self._queue_lock:
                self._current_queue_depth -= 1

    def _check_session_expiry(self) -> None:
        """Check if session has expired.

        Raises:
            SessionExpiredError: If session has expired with structured fields
        """
        # Check max messages
        if self._tool_call_count >= self._max_messages:
            raise SessionExpiredError(
                reason="max_messages_exceeded",
                limit=self._max_messages,
                observed=self._tool_call_count + 1,  # +1 for current attempt
            )

        # Check idle timeout (only if timer has started)
        if self._last_activity is not None:
            idle_time = datetime.now(timezone.utc) - self._last_activity
            if idle_time > timedelta(seconds=self._idle_timeout_seconds):
                raise SessionExpiredError(
                    reason="idle_timeout_exceeded",
                    limit=self._idle_timeout_seconds,
                    observed=int(idle_time.total_seconds()),
                )

    def get_session_state(self) -> SessionState:
        """Get current session state.

        Returns:
            Current session state
        """
        return SessionState(
            tool_call_count=self._tool_call_count,
            max_messages=self._max_messages,
            idle_timeout_seconds=self._idle_timeout_seconds,
            last_activity=self._last_activity,
            queue_depth=self._current_queue_depth,
            max_queue_depth=self._max_queue_depth,
        )

    async def reset_session(self) -> None:
        """Reset the session state."""
        self._tool_call_count = 0
        self._last_activity = None  # Timer starts on first call after reset
        await self._agent.reset()
        logger.info("Session reset")

    async def shutdown(self) -> None:
        """Shutdown the instance and cleanup resources."""
        await self._agent.shutdown()
        logger.info("SimulationInstance shutdown")

# Made with Bob