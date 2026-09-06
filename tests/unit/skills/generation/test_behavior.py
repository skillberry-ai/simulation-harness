import json

import pytest
from unittest.mock import AsyncMock, patch

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationEvidence,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages import behavior as B


def _ir() -> SpecModel:
    return SpecModel(
        api_name="Aha",
        slug="aha",
        entities=[
            Entity(
                name="Feature",
                collection="features",
                primary_key="id",
                fields=[
                    Field(name="id", type="string", required=True),
                    Field(name="price", type="integer"),
                ],
            )
        ],
        operations=[
            Operation(
                operation_id="getFeature",
                method="GET",
                path="/features/{id}",
                entity="Feature",
                kind=OperationKind.read,
            )
        ],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


WELL_FORMED = (
    "### Numeric Ranges and Ordering\n- price 10-100\n\n"
    "### Derivation Rules\n- total = sum of prices\n\n"
    "### On-Demand Generation Rules\n- deterministic price by id\n"
)


async def test_generate_behavior_returns_section() -> None:
    with patch.object(B, "call_text", AsyncMock(return_value=WELL_FORMED)):
        out = await B.generate_behavior(_ir(), llm=object(), retries=2)
    assert "### Derivation Rules" in out
    assert "total = sum of prices" in out


async def test_generate_behavior_rejects_missing_heading() -> None:
    bad = "### Numeric Ranges and Ordering\n- price 10-100\n"
    with patch.object(B, "call_text", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError):
            await B.generate_behavior(_ir(), llm=object(), retries=0)


def test_behavior_prompt_contains_required_headings() -> None:
    prompt = B._load_prompt()
    for heading in B.REQUIRED_HEADINGS:
        assert heading in prompt


def test_ops_summary_carries_description() -> None:
    ir = _ir()
    ir.evidence = {
        "getFeature": OperationEvidence(
            description="Returns a feature; total equals the sum of line prices."
        )
    }

    records = json.loads(B._ops_summary(ir))

    assert records[0]["description"] == (
        "Returns a feature; total equals the sum of line prices."
    )


def test_ops_summary_description_none_without_evidence_entry() -> None:
    records = json.loads(B._ops_summary(_ir()))
    assert records[0]["description"] is None


def test_behavior_prompt_declares_numeric_prose_authoritative() -> None:
    prompt = B._load_prompt()
    assert "are authoritative" in prompt
    assert "description" in prompt


# --- caller-gate guard -------------------------------------------------------
#
# Detected in code rather than forbidden in the prompt, because the prompt route
# was measured and rejected: the rule in `behavior.md` cut Derivation Rules by 31%
# and its numeric rules by 35% (n=12 per arm, airline, temperature 0) while
# removing no caller gates at all — 42 trials never reproduced the defect, so
# there were none to remove. This check costs the output nothing.

# The real defect, from a tau2-airline preamble.
_OBSERVED_DEFECT = (
    "### Derivation Rules\n"
    "- `calculate` returns exactly the deterministic arithmetic result.\n"
    "- `transfer_to_human_agents` is only allowed when the user explicitly asks "
    "for a human agent or the issue cannot be solved with the available tools and "
    "policy; this eligibility rule is deterministic and must be enforced even "
    "though no schema field encodes it.\n"
)


def test_observed_caller_gate_is_rejected() -> None:
    violations = B.caller_gate_violations(_OBSERVED_DEFECT)
    assert len(violations) == 1
    assert "cannot observe" in violations[0]
    assert "transfer_to_human_agents" in violations[0]


def test_the_legitimate_rule_beside_it_is_untouched() -> None:
    """Only the offending bullet is reported, not the whole subsection."""
    assert (
        B.caller_gate_violations(
            "### Derivation Rules\n"
            "- `calculate` returns exactly the deterministic arithmetic result.\n"
        )
        == []
    )


def test_enforcement_language_about_data_is_not_a_violation() -> None:
    """ "Only allowed" is ordinary in a numeric rule. A violation needs an
    unobservable actor as well, or the guard would gut legitimate content — which
    is the whole failure mode of doing this in the prompt."""
    section = (
        "### Derivation Rules\n"
        "- A refund is only allowed up to the total paid amount.\n"
        "- `total_baggages` may only exceed `nonfree_baggages` for paid bags.\n"
        "- Cancellation is only permitted while `status` is `pending`.\n"
    )
    assert B.caller_gate_violations(section) == []


def test_mentioning_a_user_without_gating_on_them_is_not_a_violation() -> None:
    section = (
        "### Derivation Rules\n"
        "- `get_user_details` must return `User.reservations` consistent with the "
        "reservation store.\n"
        "- The user's saved passengers are copied unchanged from `users`.\n"
    )
    assert B.caller_gate_violations(section) == []


def test_a_wrapped_bullet_cannot_hide_half_of_itself() -> None:
    """The two halves identify the defect together, so a hard-wrapped rule has to
    be folded back into one bullet before matching."""
    section = (
        "### Derivation Rules\n"
        "- `escalate` is only allowed when\n"
        "  the caller has confirmed with the user first.\n"
    )
    assert len(B.caller_gate_violations(section)) == 1


def _headed(body: str) -> str:
    """`body` plus the other required headings, so only the guard can fail."""
    return (
        body
        + "\n### Numeric Ranges and Ordering\n- x\n"
        + "### On-Demand Generation Rules\n- y\n"
    )


async def test_guard_is_wired_into_generation() -> None:
    """A caller gate has to reach `with_repair` as feedback, not slip through."""
    headed = _headed(_OBSERVED_DEFECT)
    with patch.object(B, "call_text", AsyncMock(return_value=headed)):
        with pytest.raises(GenerationStageError) as excinfo:
            await B.generate_behavior(_ir(), llm=object(), retries=0)
    assert "cannot observe" in str(excinfo.value)
