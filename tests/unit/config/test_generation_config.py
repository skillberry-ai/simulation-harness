import pytest

from simulation_harness.config.models import GenerationConfig, HarnessConfig
from typing import Any


@pytest.fixture
def minimal_harness_dict() -> dict[str, Any]:
    return {
        "llm": {
            "provider": "openai",
            "skill_generation_model": "m",
            "simulation_model": "m",
        },
        "skills": {"folder": "./skills-store"},
        "sessions": {"max_messages": 100, "idle_timeout_seconds": 3600},
        "mcp": {"transport": "sse"},
    }


def test_generation_defaults() -> None:
    cfg = GenerationConfig()
    assert cfg.concurrency == 5
    assert cfg.chunk_threshold == 40
    assert cfg.repair_retries == 2
    assert cfg.stage_timeout_seconds == 120
    assert cfg.classify_batch_size == 40
    assert cfg.extract.max_tokens == 8000
    assert cfg.classify.temperature == 0.0
    assert cfg.classify.max_tokens == 4000
    assert cfg.operation.temperature == 0.2
    assert cfg.operation.max_tokens == 4000


def test_generation_overrides_and_extra_forbidden() -> None:
    cfg = GenerationConfig(concurrency=8, extract={"max_tokens": 9000})
    assert cfg.concurrency == 8
    assert cfg.extract.max_tokens == 9000
    from pydantic import ValidationError

    # stale 'analyze' key must be rejected (no back-compat)
    with pytest.raises(ValidationError):
        GenerationConfig(analyze={"max_tokens": 9000})  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        GenerationConfig(unknown_field=1)  # type: ignore[call-arg]


def test_harness_config_defaults_generation(
    minimal_harness_dict: dict[str, Any],
) -> None:
    cfg = HarnessConfig(**minimal_harness_dict)
    assert isinstance(cfg.generation, GenerationConfig)
    assert cfg.generation.classify_batch_size == 40
