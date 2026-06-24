"""Shared LLM client + structured-call helpers for the generation pipeline."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr


class StructuredCallError(RuntimeError):
    """Raised when an LLM response cannot be parsed as the expected structure."""


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
    return ChatOpenAI(**kwargs)


async def call_json(llm: ChatOpenAI, system: str, user: str) -> dict | list:
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    response = await llm.ainvoke(messages)
    content = str(response.content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise StructuredCallError(f"LLM response is not valid JSON: {e}") from e


async def call_text(llm: ChatOpenAI, system: str, user: str) -> str:
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    response = await llm.ainvoke(messages)
    return str(response.content)
