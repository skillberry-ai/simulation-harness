"""Single ingress point for secret values.

Reads from process environment variables. In Kubernetes, these are populated
via `valueFrom.secretKeyRef` on the pod. In local development, pydantic-settings
also reads them from a `.env` file in the working directory.

This module is the ONLY place in the codebase that reads secret values from
the environment. All other consumers receive secrets as `SecretStr` arguments.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    """Application secrets loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    llm_api_key: SecretStr = Field(min_length=1)
    llm_api_base: str | None = Field(default=None, min_length=1)
