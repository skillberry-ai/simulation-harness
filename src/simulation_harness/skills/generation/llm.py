"""Shared LLM client + structured-call helpers for the generation pipeline."""

from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import LengthFinishReasonError
from pydantic import SecretStr


class StructuredCallError(RuntimeError):
    """Raised when an LLM response cannot be parsed as the expected structure."""


_TRUNCATED_MSG = (
    "LLM response was truncated before completion (output token limit reached); "
    "reduce scope or raise max_tokens for this stage"
)

# Set HARNESS_LLM_NO_CACHE to a truthy value ("1", "true", "yes") to bypass the
# shared LiteLLM gateway's whole-response cache. Off by default: the cache is a
# real cost/latency win for ordinary generation, and only a determinism
# measurement (scripts/check-generation-determinism.sh) needs it disabled. The
# harness reads this once per `build_chat` call, so it must be set in the
# environment the harness process itself was started with — restart the
# harness after exporting it, don't set it only in a client's shell.
_NO_CACHE_ENV_VAR = "HARNESS_LLM_NO_CACHE"
_TRUTHY = {"1", "true", "yes"}


def _no_cache_requested() -> bool:
    return os.environ.get(_NO_CACHE_ENV_VAR, "").strip().lower() in _TRUTHY


def build_chat(
    *,
    api_key: SecretStr,
    model: str,
    temperature: float,
    max_tokens: int,
    base_url: str | None,
    json_mode: bool,
) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
    if base_url:
        kwargs["base_url"] = base_url
    if _no_cache_requested():
        kwargs["extra_body"] = {"cache": {"no-cache": True}}
    return ChatOpenAI(**kwargs)


async def call_json(llm: ChatOpenAI, system: str, user: str) -> dict | list:
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    try:
        response = await llm.ainvoke(messages)
    except LengthFinishReasonError as e:
        raise StructuredCallError(_TRUNCATED_MSG) from e
    content = str(response.content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise StructuredCallError(f"LLM response is not valid JSON: {e}") from e


async def call_text(llm: ChatOpenAI, system: str, user: str) -> str:
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    try:
        response = await llm.ainvoke(messages)
    except LengthFinishReasonError as e:
        raise StructuredCallError(_TRUNCATED_MSG) from e
    return str(response.content)
