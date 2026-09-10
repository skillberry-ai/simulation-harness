"""Guards against ordering leaks in the identity rule.

The whole point of deriving identity in code is that the same spec yields the
same contract every time. These tests assert the derivation cannot depend on
dict insertion order, which is the one way a pure function can still drift.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from simulation_harness.skills.generation.stages.analyze.identity import (
    derive_identity,
)

SCHEMAS: dict[str, dict] = {
    "get_user__response": {
        "properties": {"user_id": {"type": "string"}, "name": {"type": "string"}}
    },
    "Error": {"properties": {"message": {"type": "string"}}},
    "list_orders__response": {
        "properties": {"order_id": {"type": "string"}, "total": {"type": "number"}}
    },
    "Ambiguous": {
        "properties": {"a_id": {"type": "string"}, "b_id": {"type": "string"}}
    },
}


def test_derivation_is_insensitive_to_schema_map_order() -> None:
    forward = derive_identity(SCHEMAS, synthetic=True)
    reversed_map = dict(reversed(list(SCHEMAS.items())))
    assert derive_identity(reversed_map, synthetic=True) == forward


def test_derivation_is_insensitive_to_property_order() -> None:
    forward = derive_identity(SCHEMAS, synthetic=True)
    shuffled = {
        name: {
            **schema,
            "properties": dict(reversed(list(schema["properties"].items()))),
        }
        for name, schema in SCHEMAS.items()
    }
    assert derive_identity(shuffled, synthetic=True) == forward


def test_derivation_is_repeatable() -> None:
    assert derive_identity(SCHEMAS, synthetic=True) == derive_identity(
        SCHEMAS, synthetic=True
    )


# Shaped so element-shape derivation actually runs: `items` promotes to its own
# `reference` element (Item carries a leftover `qty`, so its link_fields are
# exercised too), and `payment_history` stays `embedded` but carries a foreign-key
# annotation onto `payment_methods` — the exact shape this branch introduced and
# the one `_linked_entities` (operations.py) now has to read. Neither of these
# was covered by SCHEMAS above, which has no arrays at all, so re-deriving the
# *same* dict (as `test_derivation_is_repeatable` does) cannot catch a dict
# -iteration-order dependence that only shows up in the element-shape pass.
ELEMENT_SCHEMAS: dict[str, dict] = {
    "Order": {
        "properties": {
            "order_id": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "qty": {"type": "integer"},
                    },
                },
            },
            "payment_history": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "payment_method_id": {"type": "string"},
                        "amount": {"type": "number"},
                    },
                },
            },
        }
    },
    "PaymentMethod": {
        "properties": {"id": {"type": "string"}, "balance": {"type": "number"}}
    },
}


def test_derivation_is_stable_under_shuffled_key_insertion_order() -> None:
    """Re-deriving the same dict (as `test_derivation_is_repeatable` does) cannot
    detect a dict-iteration-order dependence, because a dict re-literal in one
    process iterates in the same insertion order every time. This shuffles the
    *insertion order* of the schema map's keys — with a fixed seed, so it cannot
    flake — and re-derives several times, checking not just the collection list
    but the pk_map and every element shape (including the foreign-key annotation
    and the reference's link_fields), which is exactly the kind of value a
    dict-order leak in the element-shape pass could silently reorder or drop.
    """
    rng = random.Random(20260908)
    baseline = derive_identity(ELEMENT_SCHEMAS, synthetic=False)
    assert baseline.collections == ["items", "orders", "payment_methods"]
    assert baseline.pk_map == {
        "items": "item_id",
        "orders": "order_id",
        "payment_methods": "id",
    }
    order = next(e for e in baseline.entities if e.collection == "orders")
    elements = dict(order.elements)
    assert elements["items"].kind == "reference"
    assert elements["items"].target_collection == "items"
    assert elements["payment_history"].kind == "embedded"
    assert elements["payment_history"].target_collection == "payment_methods"
    assert elements["payment_history"].local_key == "payment_method_id"

    for _ in range(20):
        items = list(ELEMENT_SCHEMAS.items())
        rng.shuffle(items)
        shuffled = dict(items)
        assert derive_identity(shuffled, synthetic=False) == baseline


# --- cross-interpreter guard -------------------------------------------------
#
# The three tests above all run inside one interpreter, and Python fixes string
# hash randomization per process: `set` iteration order is therefore *stable*
# within a single run, so reversing the input cannot make a `set` on an output
# path misbehave. Only two interpreters started with different PYTHONHASHSEED
# values can catch that, which is what the rest of this module does.

_CHILD_PROGRAM = """
import json
import sys
from pathlib import Path

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.stages.analyze.identity import (
    derive_identity,
)
from simulation_harness.skills.generation.stages.analyze.sources import (
    collect_sources,
)

spec_dict = json.loads(Path(sys.argv[1]).read_text())
sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
model = derive_identity(
    sources.identity, synthetic=sources.synthetic, deferred=sources.deferred
)
# Ordering is reported exactly as produced and must never be re-sorted here: a
# set leaking into an output path shows up as a *reordering* of the same values,
# so sorting on the way out would hide the one thing this probe exists to see.
json.dump(
    {
        # Proves the two children really did get different randomization. A
        # child that silently ignored PYTHONHASHSEED would make the comparison
        # in the parent vacuous.
        "hash_probe": hash("simulation-harness"),
        "collections": model.collections,
        "pk_map": list(model.pk_map.items()),
        "undecidable": list(model.undecidable),
    },
    sys.stdout,
)
"""

EXAMPLES = Path(__file__).resolve().parents[5] / "utils" / "test-client" / "examples"


def _derive_in_child(spec_path: Path, hash_seed: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-c", _CHILD_PROGRAM, str(spec_path)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
    )
    # Kept on its own line: the inline form is formatted differently by the
    # project's ruff and by the older ruff pinned in .pre-commit-config.yaml,
    # so the two gates would fight over it.
    failure = f"child with PYTHONHASHSEED={hash_seed} failed:\n{completed.stderr}"
    assert completed.returncode == 0, failure
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize(
    "filename",
    [
        "tau2_retail_openapi.json",
        "slack_web_openapi_v2_openapi3.json",
        # The only spec with a non-empty `deferred` set — the guard above
        # otherwise never exercises the `deferred`-routing code path this
        # branch added.
        "tau2_airline_openapi.json",
    ],
)
def test_derivation_is_identical_across_python_hash_seeds(filename: str) -> None:
    """The contract is identical in two interpreters with different hash seeds.

    Several ``test_identity_golden.py`` tests also pin ordered lists and so can
    also fail if a ``set`` leaks into an output-ordering path in
    ``identity.py`` — but only when hash order happens to differ from sorted
    order in that one process. This test is the one that catches that mutation
    *deterministically*, regardless of which way hash order happens to fall. It
    codifies a property that was verified by hand before the test was written
    (one hash across seeds 0, 12345 and 999983 on all four real specs), so a
    failure here means a regression, not a discovery.
    """
    spec_path = EXAMPLES / filename
    low = _derive_in_child(spec_path, "0")
    high = _derive_in_child(spec_path, "999983")

    # Were these equal, the children ignored PYTHONHASHSEED and everything
    # below would prove nothing.
    assert low["hash_probe"] != high["hash_probe"]

    assert low["collections"] == high["collections"]
    assert low["pk_map"] == high["pk_map"]
    assert low["undecidable"] == high["undecidable"]
    # No vacuous pass on an empty derivation.
    assert low["collections"]
