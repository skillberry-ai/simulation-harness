"""API response models for simulation harness."""

from datetime import datetime

from pydantic import BaseModel, Field

from simulation_harness.models.domain import SessionState


class SimulationResponse(BaseModel):
    """Response model for simulation status."""

    name: str = Field(..., description="Name of the simulation")
    status: str = Field(..., description="Current status of the simulation")
    session_state: SessionState = Field(..., description="Current session state")
    mcp_endpoint: str = Field(..., description="MCP endpoint URL")
    created_at: datetime = Field(..., description="Timestamp when simulation was created")

# Made with Bob
