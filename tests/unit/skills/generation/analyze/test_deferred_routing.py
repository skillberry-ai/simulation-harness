"""The ``deferred`` seam: entity-shaped responses the rule may not decide.

``sources.identity`` used to admit only responses declaring ``"type": "object"``
with non-empty ``properties``. Anything else entity-shaped — an array of objects,
an object that simply never declared its type — was dropped from the map
entirely, and a name absent from the map is neither derived nor undecidable: the
scoped fallback never sees it and its entity is lost with no diagnostic. (Measured
on tau2-airline: ``list_all_airports`` and ``search_direct_flight``, whose Airport
and Flight entities are missing from the generated store.)

The fix routes rather than widens: those schemas are now *present* in
``sources.identity`` — the orchestrator looks the fallback's inputs up in it by
name — and listed in ``sources.deferred`` so :func:`derive_identity` reports them
undecidable without running the rule.

These tests guard the seam directly rather than through
``test_identity_golden.py``, which would only notice a regression here as a
changed count on one spec.
"""

from __future__ import annotations

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.stages.analyze.identity import (
    derive_identity,
)
from simulation_harness.skills.generation.stages.analyze.sources import (
    collect_sources,
)

# (a) an array of objects, and (b) an object carrying a sole `*_id` that never
# declared `"type": "object"`. Both are ordinary hand-written OpenAPI.
_AIRPORT_LIST = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"iata": {"type": "string"}, "city": {"type": "string"}},
    },
}
_UNTYPED_INVOICE = {
    "properties": {
        "invoice_id": {"type": "string"},
        "total": {"type": "number"},
    }
}


def _spec() -> dict:
    def body(schema: dict) -> dict:
        return {"content": {"application/json": {"schema": schema}}}

    return {
        "openapi": "3.0.0",
        "info": {"title": "Deferred", "version": "1.0.0"},
        "paths": {
            "/airports": {
                "get": {
                    "operationId": "list_airports",
                    "responses": {"200": body(_AIRPORT_LIST)},
                }
            },
            "/invoices/{id}": {
                "get": {
                    "operationId": "get_invoice",
                    "responses": {"200": body(_UNTYPED_INVOICE)},
                }
            },
            "/orders/{id}": {
                "get": {
                    "operationId": "get_order",
                    "responses": {
                        "200": body(
                            {
                                "type": "object",
                                "properties": {"order_id": {"type": "string"}},
                            }
                        )
                    },
                }
            },
        },
    }


def test_entity_shaped_responses_are_visible_and_deferred() -> None:
    """Both shapes reach ``identity`` *and* are named in ``deferred``.

    Visible without being deferred would let the rule decide them; deferred
    without being visible would make the orchestrator's ``sources.identity[name]``
    lookup raise ``KeyError``. The seam needs both halves.
    """
    spec_dict = _spec()
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)

    assert sources.synthetic is True
    assert sorted(sources.identity) == ["get_invoice", "get_order", "list_airports"]
    assert sources.deferred == frozenset({"get_invoice", "list_airports"})
    assert sources.deferred <= set(sources.identity)


def test_deferred_responses_are_undecidable_and_coin_no_collection() -> None:
    spec_dict = _spec()
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)

    model = derive_identity(
        sources.identity, synthetic=sources.synthetic, deferred=sources.deferred
    )

    assert model.undecidable == ("get_invoice", "list_airports")
    # The one strictly-gated response still derives, so the fix did not simply
    # switch the whole path off.
    assert model.collections == ["orders"]
    assert model.pk_map == {"orders": "order_id"}


def test_the_deferred_branch_and_not_a_decline_claims_the_untyped_object() -> None:
    """Regression guard for the branch itself — the reason it cannot be deleted.

    The array declines on its own merits: no top-level ``properties``, so the rule
    finds nothing either way. The untyped object is different. It carries a sole
    ``*_id``, which on the synthetic path is exactly rule 1.4, so the moment it
    becomes visible the rule will happily *derive* it — coining an ``invoices``
    collection tagged ``"derived"``, a contract entry invented by widening
    visibility rather than read off the spec. Routing instead of widening exists
    to prevent that, and only the explicit skip delivers it.

    Passing the same map with no ``deferred`` set is what deleting the branch
    looks like; this asserts the two outcomes differ.
    """
    spec_dict = _spec()
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)

    routed = derive_identity(
        sources.identity, synthetic=sources.synthetic, deferred=sources.deferred
    )
    unrouted = derive_identity(sources.identity, synthetic=sources.synthetic)

    assert "invoices" not in routed.collections
    assert "get_invoice" in routed.undecidable
    # Without the skip the rule derives it, and does so under a "derived"
    # provenance tag it has not earned.
    assert "invoices" in unrouted.collections
    assert unrouted.pk_map["invoices"] == "invoice_id"
    assert "get_invoice" not in unrouted.undecidable
    # The array is undecidable either way — which is why the branch cannot be
    # justified by the array case alone.
    assert "list_airports" in unrouted.undecidable
