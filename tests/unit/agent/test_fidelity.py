"""End-to-end fidelity behaviour of DeepAgent, driven by a scripted chat model.

The model is fake; everything else is real: create_agent, the skill
middleware, the state tools and the store, built from the restaurant fixture.
"""

import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from simulation_harness.agent.deep_agent import DeepAgent
from simulation_harness.openapi.parser import OpenAPISpec

FIXTURE = Path(__file__).parents[2] / "fixtures" / "restaurant-reservation-api"
KINDS = {
    "searchRestaurants": "search",
    "checkAvailability": "read",
    "placeReservation": "create",
    "cancelReservation": "update",
    "listReservations": "list",
}
NEW_RESTAURANT: dict[str, Any] = {
    **json.loads((FIXTURE / "db.json").read_text())["restaurants"][0],
    "id": "rest_900",
}


class _ScriptedChat(GenericFakeChatModel):
    """Fake chat model that tolerates bind_tools, so create_agent can drive it."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        return self


def call(tool: str, args: dict[str, Any], call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="", tool_calls=[{"name": tool, "args": args, "id": call_id}]
    )


def answer(payload: Any) -> AIMessage:
    return AIMessage(content=json.dumps(payload))


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "restaurant-reservation-api"
    shutil.copytree(FIXTURE, dest)
    return dest


@pytest.fixture
async def make_agent(skill_dir: Path) -> AsyncIterator[Any]:
    agents: list[DeepAgent] = []

    def build(replies: list[AIMessage], **kwargs: Any) -> DeepAgent:
        spec = OpenAPISpec(json.loads((skill_dir / "api.json").read_text()))
        with patch(
            "simulation_harness.agent.deep_agent.ChatOpenAI",
            return_value=_ScriptedChat(messages=iter(replies)),
        ):
            agent = DeepAgent(
                api_key=SecretStr("k"),
                model="m",
                temperature=0,
                max_tokens=100,
                base_url=None,
                spec=spec,
                operations=spec.operations,
                skill_dir=skill_dir,
                **kwargs,
            )
        agents.append(agent)
        return agent

    yield build
    for agent in agents:
        await agent.shutdown()


def restaurant_count(agent: DeepAgent) -> int:
    assert agent.store_registry is not None
    return int(agent.store_registry.for_thread("default").count("restaurants"))


async def test_strict_search_cannot_insert(make_agent: Any) -> None:
    agent = make_agent(
        [
            call("state_insert", {"store": "restaurants", "entity": NEW_RESTAURANT}),
            answer({"restaurants": []}),
        ],
        fidelity="strict",
        operation_kinds=KINDS,
    )
    assert await agent.generate_response("searchRestaurants", {}) == {"restaurants": []}
    assert restaurant_count(agent) == 5


async def test_generative_search_can_insert(make_agent: Any) -> None:
    agent = make_agent(
        [
            call("state_insert", {"store": "restaurants", "entity": NEW_RESTAURANT}),
            answer({"restaurants": []}),
        ],
        operation_kinds=KINDS,
    )
    await agent.generate_response("searchRestaurants", {})
    assert restaurant_count(agent) == 6


async def test_strict_without_kinds_does_not_gate(make_agent: Any) -> None:
    agent = make_agent(
        [
            call("state_insert", {"store": "restaurants", "entity": NEW_RESTAURANT}),
            answer({"restaurants": []}),
        ],
        fidelity="strict",
    )
    await agent.generate_response("searchRestaurants", {})
    assert restaurant_count(agent) == 6


async def test_strict_request_prompt_has_no_realism_cue(make_agent: Any) -> None:
    agent = make_agent([], fidelity="strict")
    op = agent._find_operation("searchRestaurants")
    assert op is not None
    prompt = agent._create_request_prompt(op, {"city": "Boston"})
    assert "realistic" not in prompt.lower()
    assert "Fidelity: strict (closed world)" in prompt


async def test_generative_request_prompt_is_unchanged(make_agent: Any) -> None:
    agent = make_agent([])
    op = agent._find_operation("searchRestaurants")
    assert op is not None
    prompt = agent._create_request_prompt(op, {})
    assert "Generate a realistic mock response that:" in prompt
    assert "Fidelity:" not in prompt


async def test_system_prompt_follows_fidelity(make_agent: Any) -> None:
    assert "## Closed-World Data" in make_agent([], fidelity="strict").system_prompt
    assert "## Closed-World Data" not in make_agent([]).system_prompt
