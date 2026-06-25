import collections
from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages.analyze import classify as C


def _stub(oid, tag):
    return {
        "operation_id": oid,
        "method": "GET",
        "path": f"/{oid}",
        "tag": tag,
        "summary": None,
    }


def test_plan_packs_tags_without_splitting_when_under_cap():
    # tags of size 24, 21, 16, 11, 10 — all < cap 40
    sizes = {"A": 24, "B": 21, "C": 16, "D": 11, "E": 10}
    stubs = [_stub(f"{t}{i}", t) for t, n in sizes.items() for i in range(n)]
    batches = C.plan_classify_batches(stubs, cap=40)
    # no batch exceeds the cap
    assert all(len(b) <= 40 for b in batches)
    # every op covered exactly once
    assert sum(len(b) for b in batches) == sum(sizes.values())
    # no tag is split across batches
    tag_batches = collections.defaultdict(set)
    for bi, b in enumerate(batches):
        for s in b:
            tag_batches[s["tag"]].add(bi)
    assert all(len(bs) == 1 for bs in tag_batches.values())


def test_plan_splits_only_the_oversized_tag():
    stubs = [_stub(f"big{i}", "Big") for i in range(95)] + [_stub("s0", "Small")]
    batches = C.plan_classify_batches(stubs, cap=40)
    assert all(len(b) <= 40 for b in batches)
    assert sum(len(b) for b in batches) == 96
    # "Small" stays whole in exactly one batch
    small_batches = {
        bi for bi, b in enumerate(batches) for s in b if s["tag"] == "Small"
    }
    assert len(small_batches) == 1


def test_plan_empty():
    assert C.plan_classify_batches([], cap=40) == []


async def test_classify_batch_returns_records():
    stubs = [_stub("getFeature", "Features")]
    records = [
        {
            "operation_id": "getFeature",
            "entity": "Feature",
            "kind": "read",
            "patterns": ["crud"],
        }
    ]
    with patch.object(C, "call_json", AsyncMock(return_value=records)):
        out = await C.classify_batch(stubs, ["Feature"], llm=object(), retries=0)
    assert out == records


async def test_classify_batch_repairs_coverage_gap():
    stubs = [_stub("a", "T"), _stub("b", "T")]
    incomplete = [{"operation_id": "a", "entity": None, "kind": "read", "patterns": []}]
    complete = incomplete + [
        {"operation_id": "b", "entity": None, "kind": "read", "patterns": []}
    ]
    seq = iter([incomplete, complete])
    with patch.object(C, "call_json", AsyncMock(side_effect=lambda *a, **k: next(seq))):
        out = await C.classify_batch(stubs, [], llm=object(), retries=1)
    assert {r["operation_id"] for r in out} == {"a", "b"}


async def test_classify_batch_rejects_invalid_kind_and_exhausts():
    stubs = [_stub("a", "T")]
    bad = [{"operation_id": "a", "entity": None, "kind": "frobnicate", "patterns": []}]
    with patch.object(C, "call_json", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError) as exc:
            await C.classify_batch(stubs, [], llm=object(), retries=1)
    assert exc.value.stage == "classify"


async def test_classify_batch_rejects_unknown_entity():
    stubs = [_stub("a", "T")]
    bad = [{"operation_id": "a", "entity": "Ghost", "kind": "read", "patterns": []}]
    with patch.object(C, "call_json", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError):
            await C.classify_batch(stubs, ["Feature"], llm=object(), retries=0)
