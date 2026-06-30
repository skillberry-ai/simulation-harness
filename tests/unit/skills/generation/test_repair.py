import pytest

from simulation_harness.skills.generation.repair import (
    GenerationStageError,
    with_repair,
)
from typing import Any


async def test_succeeds_on_third_attempt_and_threads_feedback() -> None:
    seen_feedback = []
    outputs = iter(["bad1", "bad2", "good"])

    async def produce(feedback: Any) -> Any:
        seen_feedback.append(feedback)
        return next(outputs)

    def validate(artifact: Any) -> Any:
        return [] if artifact == "good" else [f"artifact was {artifact}"]

    result = await with_repair(produce, validate, stage="t", retries=2)
    assert result == "good"
    assert seen_feedback[0] is None
    assert seen_feedback[1] == ["artifact was bad1"]
    assert seen_feedback[2] == ["artifact was bad2"]


async def test_raises_after_exhausting_retries() -> None:
    async def produce(feedback: Any) -> str:
        return "always-bad"

    def validate(artifact: Any) -> list[Any]:
        return ["nope"]

    with pytest.raises(GenerationStageError) as exc:
        await with_repair(produce, validate, stage="schema", retries=2)
    assert exc.value.stage == "schema"
    assert exc.value.errors == ["nope"]


async def test_passes_first_time_no_repair() -> None:
    calls = []

    async def produce(feedback: Any) -> str:
        calls.append(feedback)
        return "ok"

    result = await with_repair(produce, lambda a: [], stage="t", retries=2)
    assert result == "ok"
    assert calls == [None]
