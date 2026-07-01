"""API request models for simulation harness."""

from typing import Any

from pydantic import BaseModel, Field


class CreateSimulationRequest(BaseModel):
    """Request model for creating a simulation."""

    openapi_spec: dict[str, Any] = Field(
        ..., description="OpenAPI specification as a dictionary"
    )
    name: str | None = Field(
        default=None,
        description="Simulation name override; defaults to spec info.title",
    )
    regenerate_skill: bool = Field(
        default=False, description="Whether to regenerate the skill even if it exists"
    )
    mcp_port: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="Port to expose the MCP server on. Defaults to the harness port.",
    )


class StartSimulationRequest(BaseModel):
    """Request model for starting a simulation from baked artifacts."""

    name: str = Field(..., description="Name of the skill whose artifacts to start")
    mcp_port: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="Port to expose the MCP server on. Defaults to the harness port.",
    )


# Made with Bob
