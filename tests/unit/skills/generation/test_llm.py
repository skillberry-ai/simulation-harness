from unittest.mock import AsyncMock, MagicMock, patch

from pathlib import Path

import httpx
import openai
import pytest
from pydantic import SecretStr

from simulation_harness.skills.generation import llm as llmmod
from simulation_harness.skills.generation.llm import (
    StructuredCallError,
    build_chat,
    call_json,
    is_fatal_llm_error,
    call_text,
)


def test_build_chat_json_mode_sets_response_format() -> None:
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


def test_build_chat_text_mode_has_no_response_format() -> None:
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


@pytest.fixture(autouse=True)
def _dotenv_free_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """build_chat() consults `.env`; keep the developer's own out of these tests."""
    monkeypatch.chdir(tmp_path_factory.mktemp("dotenv-free"))


def test_build_chat_omits_extra_body_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HARNESS_LLM_NO_CACHE", raising=False)
    with patch.object(llmmod, "ChatOpenAI") as mock:
        build_chat(
            api_key=SecretStr("k"),
            model="m",
            temperature=0.0,
            max_tokens=100,
            base_url=None,
            json_mode=False,
        )
        assert "extra_body" not in mock.call_args.kwargs


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " Yes "])
def test_build_chat_sets_extra_body_when_no_cache_env_is_truthy(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HARNESS_LLM_NO_CACHE", value)
    with patch.object(llmmod, "ChatOpenAI") as mock:
        build_chat(
            api_key=SecretStr("k"),
            model="m",
            temperature=0.0,
            max_tokens=100,
            base_url=None,
            json_mode=False,
        )
        assert mock.call_args.kwargs["extra_body"] == {"cache": {"no-cache": True}}


@pytest.mark.parametrize("value", ["", "0", "false", "no", "nope"])
def test_build_chat_omits_extra_body_when_no_cache_env_is_falsy(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HARNESS_LLM_NO_CACHE", value)
    with patch.object(llmmod, "ChatOpenAI") as mock:
        build_chat(
            api_key=SecretStr("k"),
            model="m",
            temperature=0.0,
            max_tokens=100,
            base_url=None,
            json_mode=False,
        )
        assert "extra_body" not in mock.call_args.kwargs


async def test_call_json_parses_object() -> None:
    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value=MagicMock(content='{"a": 1}'))
    assert await call_json(fake, "sys", "usr") == {"a": 1}


async def test_call_json_raises_on_bad_json() -> None:
    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value=MagicMock(content="not json"))
    with pytest.raises(StructuredCallError):
        await call_json(fake, "sys", "usr")


async def test_call_text_returns_content() -> None:
    fake = MagicMock()
    fake.ainvoke = AsyncMock(return_value=MagicMock(content="hello"))
    assert await call_text(fake, "sys", "usr") == "hello"


async def test_call_json_wraps_length_truncation_as_structured_error() -> None:
    from openai import LengthFinishReasonError

    fake = MagicMock()
    fake.ainvoke = AsyncMock(
        side_effect=LengthFinishReasonError(completion=MagicMock())
    )
    with pytest.raises(StructuredCallError) as exc:
        await call_json(fake, "sys", "usr")
    assert "truncated" in str(exc.value).lower()


async def test_call_text_wraps_length_truncation_as_structured_error() -> None:
    from openai import LengthFinishReasonError

    fake = MagicMock()
    fake.ainvoke = AsyncMock(
        side_effect=LengthFinishReasonError(completion=MagicMock())
    )
    with pytest.raises(StructuredCallError) as exc:
        await call_text(fake, "sys", "usr")
    assert "truncated" in str(exc.value).lower()


def test_build_chat_reads_no_cache_from_dotenv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Issue #13: every HARNESS_* variable resolves the same way, `.env` included.

    The determinism script exports this, but a developer reproducing a run puts
    it in `.env` next to the rest of their harness settings.
    """
    monkeypatch.delenv("HARNESS_LLM_NO_CACHE", raising=False)
    (tmp_path / ".env").write_text("HARNESS_LLM_NO_CACHE=1\n")
    monkeypatch.chdir(tmp_path)
    with patch.object(llmmod, "ChatOpenAI") as mock:
        build_chat(
            api_key=SecretStr("k"),
            model="m",
            temperature=0.0,
            max_tokens=100,
            base_url=None,
            json_mode=False,
        )
        assert mock.call_args.kwargs["extra_body"] == {"cache": {"no-cache": True}}


def test_process_env_falsy_beats_truthy_dotenv_no_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Explicitly turning it off in the shell must not be undone by a stale `.env`."""
    (tmp_path / ".env").write_text("HARNESS_LLM_NO_CACHE=1\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HARNESS_LLM_NO_CACHE", "0")
    with patch.object(llmmod, "ChatOpenAI") as mock:
        build_chat(
            api_key=SecretStr("k"),
            model="m",
            temperature=0.0,
            max_tokens=100,
            base_url=None,
            json_mode=False,
        )
        assert "extra_body" not in mock.call_args.kwargs


def _api_error(cls: type, status: int) -> Exception:
    """Build a real openai APIStatusError subclass, not a stand-in.

    The handler under test dispatches on exception type, so a MagicMock or a
    bare RuntimeError would prove nothing about the production path.
    """
    request = httpx.Request("POST", "https://gateway.example.com/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return cls("boom", response=response, body=None)


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (openai.AuthenticationError, 401),
        (openai.PermissionDeniedError, 403),
        (openai.NotFoundError, 404),
    ],
)
def test_auth_and_model_access_errors_are_fatal(cls: type, status: int) -> None:
    """A bad key, a model the team can't reach, or a name the gateway doesn't
    know are all settings problems. No later call can succeed, so no stage
    should treat them as recoverable.
    """
    assert is_fatal_llm_error(_api_error(cls, status)) is True


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (openai.RateLimitError, 429),
        (openai.InternalServerError, 500),
    ],
)
def test_transient_errors_are_not_fatal(cls: type, status: int) -> None:
    """429/5xx are exactly what a per-stage degrade exists for."""
    assert is_fatal_llm_error(_api_error(cls, status)) is False


def test_non_api_errors_are_not_fatal() -> None:
    assert is_fatal_llm_error(RuntimeError("connection reset")) is False
    assert is_fatal_llm_error(StructuredCallError("bad json")) is False
