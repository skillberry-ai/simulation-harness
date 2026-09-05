"""API request models for simulation harness."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateSimulationRequest(BaseModel):
    """Request model for creating a simulation."""

    # Unknown fields are rejected rather than ignored. pydantic's default is
    # extra="ignore", which silently drops a misspelled key and leaves its field
    # at the default -- the request still succeeds, having done something other
    # than what the caller asked. That cost real debugging time: the determinism
    # check posted `regenerate: true` instead of `regenerate_skill: true` and
    # reused a cached skill on every run while reporting success. A 422 naming
    # the offending field is the cheaper failure.
    model_config = ConfigDict(extra="forbid")

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

    # Unknown fields are rejected, for the reason given on
    # CreateSimulationRequest above.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Name of the skill whose artifacts to start")
    mcp_port: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="Port to expose the MCP server on. Defaults to the harness port.",
    )


# Made with Bob
