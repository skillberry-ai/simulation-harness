"""Bounded validate → re-prompt → retry loop shared by all generation stages."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class GenerationStageError(RuntimeError):
    """A generation stage produced invalid output after exhausting repairs."""

    def __init__(self, stage: str, errors: list[str]) -> None:
        self.stage = stage
        self.errors = list(errors)
        super().__init__(f"stage '{stage}' failed validation: {'; '.join(errors)}")


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
