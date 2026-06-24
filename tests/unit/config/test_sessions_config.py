# tests/unit/config/test_sessions_config.py
"""Tests for session configuration, notably the agent recursion limit.

The skill-loading runtime is a multi-step ReAct agent (progressive disclosure
plus state tools), so it needs a recursion budget well above the legacy
single-call default of 10. The limit must be configurable and default high
enough that a normal tool call does not exhaust it.
"""

import pytest

from simulation_harness.config.models import HarnessConfig, SessionsConfig


def test_agent_recursion_limit_default():
    cfg = SessionsConfig(max_messages=10, idle_timeout_seconds=60)
    assert cfg.agent_recursion_limit == 50


def test_agent_recursion_limit_override():
    cfg = SessionsConfig(
        max_messages=10,
        idle_timeout_seconds=60,
        agent_recursion_limit=80,
    )
    assert cfg.agent_recursion_limit == 80


def test_agent_recursion_limit_must_be_positive():
    with pytest.raises(ValueError):
        SessionsConfig(
            max_messages=10,
            idle_timeout_seconds=60,
            agent_recursion_limit=0,
        )


def test_harness_config_includes_recursion_default(minimal_harness_kwargs):
    cfg = HarnessConfig(**minimal_harness_kwargs)
    assert cfg.sessions.agent_recursion_limit == 50


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
