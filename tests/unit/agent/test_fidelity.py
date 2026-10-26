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
from simulation_harness.agent.grounding import Ungrounded
from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.utils.errors import UngroundedResponseError

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


GROUNDED = {"restaurants": [{"id": "rest_001", "name": "The Italian Corner"}]}
INVENTED = {"restaurants": [{"id": "rest_999", "name": "Zyxwv Bistro"}]}


async def test_grounded_strict_response_passes(make_agent: Any) -> None:
    seen: list[list[Ungrounded]] = []
    agent = make_agent(
        [answer(GROUNDED)],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
        on_ungrounded=seen.append,
    )
    assert await agent.generate_response("searchRestaurants", {}) == GROUNDED
    assert seen == []


async def test_report_mode_returns_response_and_reports(make_agent: Any) -> None:
    seen: list[list[Ungrounded]] = []
    agent = make_agent(
        [answer(INVENTED)],
        fidelity="strict",
        operation_kinds=KINDS,
        on_ungrounded=seen.append,
    )
    assert await agent.generate_response("searchRestaurants", {}) == INVENTED
    assert [u.value for u in seen[0]] == ["rest_999", "Zyxwv Bistro"]


async def test_enforce_mode_raises_with_details(make_agent: Any) -> None:
    seen: list[list[Ungrounded]] = []
    agent = make_agent(
        [answer(INVENTED)],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
        on_ungrounded=seen.append,
    )
    with pytest.raises(UngroundedResponseError) as exc:
        await agent.generate_response("searchRestaurants", {})
    assert exc.value.operation_id == "searchRestaurants"
    assert exc.value.ungrounded == [
        {"path": "$.restaurants[0].id", "value": "rest_999"},
        {"path": "$.restaurants[0].name", "value": "Zyxwv Bistro"},
    ]
    assert len(seen) == 1


async def test_enforce_reports_at_most_ten_values(make_agent: Any) -> None:
    many = {"items": [f"Zyxwv-{i:02d}" for i in range(15)]}
    agent = make_agent(
        [answer(many)],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
    )
    with pytest.raises(UngroundedResponseError) as exc:
        await agent.generate_response("searchRestaurants", {})
    assert len(exc.value.ungrounded) == 10


async def test_generative_mode_never_checks(make_agent: Any) -> None:
    seen: list[list[Ungrounded]] = []
    agent = make_agent(
        [answer(INVENTED)], strict_grounding="enforce", on_ungrounded=seen.append
    )
    assert await agent.generate_response("searchRestaurants", {}) == INVENTED
    assert seen == []


async def test_refused_write_then_grounded_answer_succeeds(make_agent: Any) -> None:
    agent = make_agent(
        [
            call("state_insert", {"store": "restaurants", "entity": NEW_RESTAURANT}),
            answer({"restaurants": []}),
        ],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
    )
    assert await agent.generate_response("searchRestaurants", {}) == {"restaurants": []}


async def test_refused_write_is_reported_with_failure(make_agent: Any) -> None:
    agent = make_agent(
        [
            call("state_insert", {"store": "restaurants", "entity": NEW_RESTAURANT}),
            answer(INVENTED),
        ],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
    )
    with pytest.raises(UngroundedResponseError) as exc:
        await agent.generate_response("searchRestaurants", {})
    assert exc.value.refused_writes == [
        {"tool": "state_insert", "store": "restaurants"}
    ]


async def test_refused_writes_are_per_call(make_agent: Any) -> None:
    agent = make_agent(
        [
            call("state_insert", {"store": "restaurants", "entity": NEW_RESTAURANT}),
            answer({"restaurants": []}),
            answer(INVENTED),
        ],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
    )
    await agent.generate_response("searchRestaurants", {})
    with pytest.raises(UngroundedResponseError) as exc:
        await agent.generate_response("searchRestaurants", {})
    assert exc.value.refused_writes == []


async def test_strict_create_returning_inserted_row_is_grounded(
    make_agent: Any,
) -> None:
    reservation = {
        **json.loads((FIXTURE / "db.json").read_text())["reservations"][0],
        "id": "reservation_new_777",
        "guest_name": "Ada Byron",
        "confirmation_code": "CONF-NEW777",
    }
    agent = make_agent(
        [
            call("state_insert", {"store": "reservations", "entity": reservation}),
            answer(reservation),
        ],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
    )
    assert await agent.generate_response("placeReservation", {}) == reservation


async def test_rejection_is_carried_into_next_prompt(make_agent: Any) -> None:
    agent = make_agent(
        [answer(INVENTED)],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
    )
    with pytest.raises(UngroundedResponseError):
        await agent.generate_response("searchRestaurants", {})
    rejected = agent._pending_rejections["default"]
    op = agent._find_operation("searchRestaurants")
    assert op is not None
    prompt = agent._create_request_prompt(op, {}, rejected)
    assert "Your previous response was rejected" in prompt
    assert "'Zyxwv Bistro'" in prompt


async def test_reset_clears_pending_rejection(make_agent: Any) -> None:
    agent = make_agent(
        [answer(INVENTED)],
        fidelity="strict",
        strict_grounding="enforce",
        operation_kinds=KINDS,
    )
    with pytest.raises(UngroundedResponseError):
        await agent.generate_response("searchRestaurants", {})
    await agent.reset()
    assert agent._pending_rejections == {}
