from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from simulation_harness.skills.generation import llm as llmmod
from simulation_harness.skills.generation.llm import (
    StructuredCallError,
    build_chat,
    call_json,
    call_text,
)


def test_build_chat_json_mode_sets_response_format():
    with patch.object(llmmod, "ChatOpenAI") as mock:
        build_chat(
            api_key=SecretStr("k"),
            model="m",
            temperature=0.0,
            max_tokens=100,
            base_url=None,
            json_mode=True,
        )
        kwargs = mock.call_args.kwargs
        assert kwargs["model"] == "m"
        assert kwargs["max_tokens"] == 100
        assert kwargs["model_kwargs"] == {"response_format": {"type": "json_object"}}


def test_build_chat_text_mode_has_no_response_format():
    with patch.object(llmmod, "ChatOpenAI") as mock:
        build_chat(
            api_key=SecretStr("k"),
            model="m",
            temperature=0.2,
            max_tokens=100,
            base_url="http://x",
            json_mode=False,
        )
        kwargs = mock.call_args.kwargs
        assert kwargs.get("model_kwargs", {}) == {}
        assert kwargs["base_url"] == "http://x"


async def test_call_json_parses_object():
    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value=MagicMock(content='{"a": 1}'))
    assert await call_json(fake, "sys", "usr") == {"a": 1}


async def test_call_json_raises_on_bad_json():
    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value=MagicMock(content="not json"))
    with pytest.raises(StructuredCallError):
        await call_json(fake, "sys", "usr")


async def test_call_text_returns_content():
    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value=MagicMock(content="hello"))
    assert await call_text(fake, "sys", "usr") == "hello"
