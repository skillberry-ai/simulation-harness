"""Core domain models for simulation harness."""

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, computed_field


class SimulationSpec(BaseModel):
    """Specification for creating a simulation."""

    name: str = Field(..., description="Name of the simulation")
    openapi_spec: dict[str, Any] = Field(
        ..., description="OpenAPI specification as a dictionary"
    )
    regenerate_skill: bool = Field(
        default=False, description="Whether to regenerate the skill even if it exists"
    )


class SessionState(BaseModel):
    """Current session state with counters and limits."""

    tool_call_count: int = Field(
        ..., ge=0, description="Number of tool calls made in this session"
    )
    max_messages: int = Field(
        ..., gt=0, description="Maximum number of messages allowed in this session"
    )
    idle_timeout_seconds: int = Field(..., gt=0, description="Idle timeout in seconds")
    last_activity: Optional[datetime] = Field(
        ..., description="Timestamp of last activity (None if timer hasn't started)"
    )
    queue_depth: int = Field(..., ge=0, description="Current queue depth")
    max_queue_depth: int = Field(..., gt=0, description="Maximum queue depth allowed")

    @computed_field
    @property
    def seconds_since_last_call(self) -> Optional[int]:
        """Compute seconds since last tool call."""
        if self.last_activity is None:
            return None
        delta = datetime.now(timezone.utc) - self.last_activity
        return int(delta.total_seconds())


class ToolCallResult(BaseModel):
    """Result of a tool execution."""

    success: bool = Field(..., description="Whether the tool call succeeded")
    content: str = Field(..., description="Content returned by the tool")
    error: Optional[str] = Field(
        default=None, description="Error message if the tool call failed"
    )


# Made with Bob
