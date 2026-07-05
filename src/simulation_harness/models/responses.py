"""API response models for simulation harness."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from simulation_harness.models.domain import SessionState


class ProgressPayload(BaseModel):
    """Progress payload embedded in SimulationResponse."""

    phase: Optional[str] = Field(
        None,
        description="Current phase: skill_generation | agent_init | None",
    )
    started_at: datetime = Field(..., description="Creation start time")
    updated_at: datetime = Field(..., description="Last status change time")


class ErrorPayload(BaseModel):
    """Error payload embedded in SimulationResponse for failed simulations."""

    code: str = Field(..., description="Stable error code")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional structured fields"
    )


class SimulationResponse(BaseModel):
    """Response model for simulation status."""

    name: str = Field(..., description="Name of the simulation")
    status: str = Field(
        ...,
        description="One of: pending | generating_skill | initializing | ready | failed",
    )
    session_state: Optional[SessionState] = Field(
        None,
        description="Session state — populated only when status=ready.",
    )
    mcp_url: Optional[str] = Field(
        None,
        description="Full MCP endpoint URL — populated only when status=ready.",
    )
    created_at: datetime = Field(
        ..., description="Timestamp when simulation was declared"
    )
    progress: ProgressPayload = Field(..., description="Creation progress info")
    error: Optional[ErrorPayload] = Field(
        None, description="Failure details — populated only when status=failed."
    )


class SimulationBundleResponse(BaseModel):
    """Full generated skill bundle for the active skill."""

    name: str = Field(..., description="Name of the active skill/simulation")
    files: dict[str, str] = Field(
        ...,
        description=(
            "Bundle filename -> verbatim file contents. Always includes SKILL.md, "
            "schema.json, db.json, api.json; scenarios.json is present only when it "
            "exists on disk."
        ),
    )
    sizes: dict[str, int] = Field(
        ...,
        description="Bundle filename -> uncompressed content size in bytes.",
    )


# Made with Bob
