"""Bounded validate → re-prompt → retry loop shared by all generation stages."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class GenerationStageError(RuntimeError):
    """A generation stage produced invalid output after exhausting repairs."""

    def __init__(self, stage: str, errors: list[str]) -> None:
        self.stage = stage
        self.errors = list(errors)
        super().__init__(f"stage '{stage}' failed validation: {'; '.join(errors)}")


class StageTimeoutError(RuntimeError):
    """A generation stage exceeded its per-stage timeout budget.

    Distinct from a bare ``asyncio.TimeoutError`` so callers can tell a stalled
    stage apart from the outer creation-budget timeout, and carry which stage
    stalled. Not a subclass of ``TimeoutError`` on purpose — the outer
    ``asyncio.wait_for`` budget in ``SimulationCreator`` must remain
    distinguishable.
    """

    def __init__(self, stage: str, timeout: float) -> None:
        self.stage = stage
        self.timeout = timeout
        super().__init__(f"generation stage '{stage}' timed out after {timeout:.0f}s")


async def guard_timeout(
    coro: "Awaitable[T]", *, stage: str, timeout: float | None
) -> T:
    """Run ``coro`` under a per-stage timeout, tagging expiry with the stage name.

    Converts ``asyncio.TimeoutError`` into :class:`StageTimeoutError` so the
    stalled stage is identifiable downstream. A ``None`` timeout disables the
    guard (awaits ``coro`` directly).
    """
    if timeout is None:
        return await coro
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError as e:
        raise StageTimeoutError(stage, timeout) from e


async def with_repair(
    produce: Callable[[list[str] | None], "Awaitable[T]"],
    validate: Callable[[T], list[str]],
    *,
    stage: str,
    retries: int,
) -> T:
    feedback: list[str] | None = None
    errors: list[str] = []
    for _attempt in range(retries + 1):
        artifact = await produce(feedback)
        errors = validate(artifact)
        if not errors:
            return artifact
        feedback = errors
    raise GenerationStageError(stage, errors)
