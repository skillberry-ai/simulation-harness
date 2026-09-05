from pathlib import Path

import pytest
import yaml

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
    assert cfg.operation.temperature == 0.0
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


def test_generation_behavior_defaults() -> None:
    cfg = GenerationConfig()
    assert cfg.behavior_enabled is True
    assert cfg.behavior.temperature == 0.0
    assert cfg.behavior.max_tokens == 3000


def test_harness_config_defaults_generation(
    minimal_harness_dict: dict[str, Any],
) -> None:
    cfg = HarnessConfig(**minimal_harness_dict)
    assert isinstance(cfg.generation, GenerationConfig)
    assert cfg.generation.classify_batch_size == 40


def test_shipped_harness_yaml_stage_temperatures() -> None:
    """The shipped YAML overrides the model defaults, so pin its stage params.

    Every stage that produces a structured artifact runs deterministically;
    only scenario prose samples above 0. behavior's max_tokens is asserted
    because a stage entry that omits max_tokens falls back to the StageParams
    field default (8000), not to the per-stage default_factory value (3000).
    """
    repo_root = Path(__file__).resolve().parents[3]
    data = yaml.safe_load((repo_root / "config" / "harness.yaml").read_text())
    gen = HarnessConfig(**data).generation
    assert gen.extract.temperature == 0.0
    assert gen.classify.temperature == 0.0
    assert gen.operation.temperature == 0.0
    assert gen.schema_seed.temperature == 0.0
    assert gen.behavior.temperature == 0.0
    assert gen.behavior.max_tokens == 3000
    assert gen.scenarios.temperature == 0.4
    # behavior_enabled is not spelled out in the YAML; it must stay on by default
    assert gen.behavior_enabled is True
