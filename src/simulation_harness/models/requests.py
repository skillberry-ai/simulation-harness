"""API request models for simulation harness."""

from typing import Any

from pydantic import BaseModel, Field


class CreateSimulationRequest(BaseModel):
    """Request model for creating a simulation."""

    openapi_spec: dict[str, Any] = Field(..., description="OpenAPI specification as a dictionary")
    name: str | None = Field(default=None, description="Simulation name override; defaults to spec info.title")
    regenerate_skill: bool = Field(default=False, description="Whether to regenerate the skill even if it exists")

# Made with Bob
