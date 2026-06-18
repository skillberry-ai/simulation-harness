"""Pydantic models for configuration."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransportType(str, Enum):
    """Supported transport types for MCP communication."""

    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class LLMConfig(BaseModel):
    """LLM provider configuration (non-secret).

    Secret values (API key, optional API base) are loaded separately via
    simulation_harness.config.Secrets. This model contains only non-secret
    tuning parameters.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., description="LLM provider (e.g., 'openai')")
    skill_generation_model: str = Field(..., description="Model for skill generation")
    simulation_model: str = Field(..., description="Model for simulation runtime")
    temperature: float = Field(0, ge=0, le=2, description="Sampling temperature")
    max_tokens: Optional[int] = Field(
        None, gt=0, description="Maximum tokens per request"
    )


class SkillsConfig(BaseModel):
    """Skills folder configuration."""

    folder: str = Field(..., description="Path to skills directory")


class SessionsConfig(BaseModel):
    """Session limits configuration."""

    max_messages: int = Field(..., gt=0, description="Maximum tool calls per session")
    idle_timeout_seconds: int = Field(..., gt=0, description="Idle timeout in seconds")
    max_concurrent_queue_depth: int = Field(
        8, gt=0, description="Maximum concurrent queue depth"
    )


class CreationConfig(BaseModel):
    """Async simulation creation configuration."""

    model_config = ConfigDict(extra="forbid")

    max_duration_seconds: int = Field(
        600,
        gt=0,
        description="Wall-clock budget for async simulation creation; "
        "exceeded creations transition to failed with code 'creation_timeout'.",
    )


class MCPConfig(BaseModel):
    """MCP transport configuration."""

    transport: TransportType = Field(..., description="MCP transport type")


class ServerSettings(BaseModel):
    """Server host and port configuration."""

    host: str = Field("localhost", description="Host to bind the server to")
    port: int = Field(8000, ge=1, le=65535, description="Port to bind the server to")


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(
        "INFO", description="Log level (DEBUG/INFO/WARNING/ERROR/CRITICAL)"
    )
    destination_folder: str = Field("./logs", description="Directory for log files")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """Validate that level is a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return v


class HarnessConfig(BaseModel):
    """Complete harness configuration (non-secret)."""

    llm: LLMConfig
    skills: SkillsConfig
    sessions: SessionsConfig
    creation: CreationConfig = Field(
        default_factory=CreationConfig,
        description="Async simulation-creation tuning.",
    )
    mcp: MCPConfig
    server: ServerSettings = Field(
        default_factory=ServerSettings, description="Server configuration"
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig, description="Logging configuration"
    )


# Made with Bob
