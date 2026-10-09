"""Shared LLM client + structured-call helpers for the generation pipeline."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import APIStatusError, LengthFinishReasonError
from pydantic import SecretStr

from simulation_harness.config.env_source import llm_no_cache_requested


class StructuredCallError(RuntimeError):
    """Raised when an LLM response cannot be parsed as the expected structure."""


_TRUNCATED_MSG = (
    "LLM response was truncated before completion (output token limit reached); "
    "reduce scope or raise max_tokens for this stage"
)

# The gateway cache bypass is shared with the runtime simulator; see
# config.env_source.llm_no_cache_requested. build_chat reads it per call.

# Statuses that no retry, repair, or per-stage degrade can recover from: the key
# is wrong (401), the team cannot reach the model (403), or the endpoint has
# never heard of it (404). A stage that softens one of these into a warning just
# defers the same failure to the next call and buries the cause above the
# traceback — which is how issue #13's 403 was misread as a generation problem.
_FATAL_STATUS_CODES = frozenset({401, 403, 404})


def is_fatal_llm_error(error: BaseException) -> bool:
    """True when ``error`` is a configuration fault, not a transient one.

    Callers that degrade gracefully on LLM failure should re-raise these instead,
    so the operator sees the credential or model-name problem directly.
    """
    return (
        isinstance(error, APIStatusError) and error.status_code in _FATAL_STATUS_CODES
    )


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
    if llm_no_cache_requested():
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
