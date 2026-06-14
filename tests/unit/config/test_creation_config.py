# tests/unit/config/test_creation_config.py
"""Tests for creation configuration."""

import pytest

from simulation_harness.config.models import CreationConfig, HarnessConfig


def test_creation_config_default():
    cfg = CreationConfig()
    assert cfg.max_duration_seconds == 120


def test_creation_config_must_be_positive():
    with pytest.raises(ValueError):
        CreationConfig(max_duration_seconds=0)


def test_harness_config_includes_creation_default(minimal_harness_kwargs):
    cfg = HarnessConfig(**minimal_harness_kwargs)
    assert cfg.creation.max_duration_seconds == 120


@pytest.fixture
def minimal_harness_kwargs():
    return {
        "llm": {
            "provider": "openai",
            "skill_generation_model": "gpt-4",
            "simulation_model": "gpt-4",
            "temperature": 0,
        },
        "skills": {"folder": "./skills"},
        "sessions": {
            "max_messages": 10,
            "idle_timeout_seconds": 60,
            "max_concurrent_queue_depth": 8,
        },
        "mcp": {"transport": "sse"},
    }
