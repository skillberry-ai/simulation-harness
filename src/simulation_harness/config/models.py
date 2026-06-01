"""Pydantic models for configuration."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TransportType(str, Enum):
    """Supported transport types for MCP communication."""

    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: str = Field(..., description="LLM provider (e.g., 'openai')")
    api_key: Optional[str] = Field(None, description="Literal API key")
    api_key_env: Optional[str] = Field(
        None, description="Environment variable name for API key"
    )
    api_base: Optional[str] = Field(None, description="Optional API base URL override")
    api_base_env: Optional[str] = Field(
        None, description="Environment variable for API base URL"
    )
    skill_generation_model: str = Field(..., description="Model for skill generation")
    simulation_model: str = Field(..., description="Model for simulation runtime")
    temperature: float = Field(0, ge=0, le=2, description="Sampling temperature")
    max_tokens: Optional[int] = Field(
        None, gt=0, description="Maximum tokens per request"
    )

    @model_validator(mode="after")
    def validate_api_key_config(self) -> "LLMConfig":
        """Validate that at least one of api_key or api_key_env is provided."""
        has_api_key = self.api_key is not None
        has_api_key_env = self.api_key_env is not None

        if not has_api_key and not has_api_key_env:
            raise ValueError("Either api_key or api_key_env must be provided")

        return self


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


class MCPConfig(BaseModel):
    """MCP transport configuration."""

    transport: TransportType = Field(..., description="MCP transport type")


class ServerSettings(BaseModel):
    """Server host and port configuration.

    Examples:
        Default (localhost only):
            ServerSettings()  # host="localhost", port=8000

        Bind to all interfaces:
            ServerSettings(host="0.0.0.0", port=8000)

        Custom port:
            ServerSettings(host="localhost", port=9000)
    """

    host: str = Field("localhost", description="Host to bind the server to")
    port: int = Field(8000, ge=1, le=65535, description="Port to bind the server to")


class LoggingConfig(BaseModel):
    """Logging configuration.

    Examples:
        Default (INFO level, ./logs):
            LoggingConfig()

        Debug logging to custom folder:
            LoggingConfig(level="DEBUG", destination_folder="/var/log/harness")
    """

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
    """Complete harness configuration."""

    llm: LLMConfig
    skills: SkillsConfig
    sessions: SessionsConfig
    mcp: MCPConfig
    server: ServerSettings = Field(
        default_factory=ServerSettings, description="Server configuration"
    )
    logging: LoggingConfig = Field(
        default_factory=LoggingConfig, description="Logging configuration"
    )


# Backward compatibility - kept for legacy ServerConfig usage
class ServerConfig(BaseModel):
    """Configuration for the MCP server (legacy)."""

    command: str
    args: list[str]
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    transport: TransportType

    @model_validator(mode="after")
    def validate_api_key_config(self) -> "ServerConfig":
        """Validate that exactly one of api_key or api_key_env is provided."""
        has_api_key = self.api_key is not None
        has_api_key_env = self.api_key_env is not None

        if has_api_key and has_api_key_env:
            raise ValueError("Cannot provide both api_key and api_key_env")

        if not has_api_key and not has_api_key_env:
            raise ValueError("Either api_key or api_key_env must be provided")

        return self


# Made with Bob
