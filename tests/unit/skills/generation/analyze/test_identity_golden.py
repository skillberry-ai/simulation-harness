"""Contract lock: the derived contract for each checked-in example spec.

Every value here was measured against the specs in the repo. A change to any of
them is a change to the runtime contract of an already-generated skill —
``state/loader.py`` reads collections and primary keys back out of
``schema.json`` — so a diff here is a finding to report, never a golden to
refresh.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.stages.analyze.identity import (
    derive_identity,
)
from simulation_harness.skills.generation.stages.analyze.sources import (
    collect_sources,
)

EXAMPLES = Path(__file__).resolve().parents[5] / "utils" / "test-client" / "examples"


def _derive(filename: str) -> tuple[list[str], dict[str, str], list[str]]:
    spec_dict = json.loads((EXAMPLES / filename).read_text())
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
    model = derive_identity(sources.identity, synthetic=sources.synthetic)
    return model.collections, model.pk_map, list(model.undecidable)


def test_tau2_retail_contract() -> None:
    collections, pk_map, undecidable = _derive("tau2_retail_openapi.json")
    assert collections == [
        "items",
        "orders",
        "payment_methods",
        "products",
        "trackings",
        "users",
    ]
    assert pk_map == {
        "items": "item_id",
        "orders": "order_id",
        "payment_methods": "payment_method_id",
        "products": "product_id",
        "trackings": "tracking_id",
        "users": "user_id",
    }
    assert undecidable == [
        "exchange_delivered_order_items",
        "get_order_details",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "return_delivered_order_items",
    ]


def test_tau2_airline_contract() -> None:
    collections, pk_map, undecidable = _derive("tau2_airline_openapi.json")
    assert collections == ["payments", "reservations", "users"]
    assert pk_map == {
        "payments": "payment_id",
        "reservations": "reservation_id",
        "users": "user_id",
    }
    assert undecidable == [
        "get_reservation_details",
        "update_reservation_baggages",
        "update_reservation_flights",
        "update_reservation_passengers",
    ]


def test_reservation_service_contract() -> None:
    collections, pk_map, undecidable = _derive("reservation-service_openapi.json")
    assert collections == ["reservations", "restaurants"]
    assert pk_map == {"reservations": "id", "restaurants": "id"}
    # Error/Location/AvailabilitySlot/CancellationReceipt are exactly the cases
    # the deterministic rule must refuse to guess at: value objects and error
    # envelopes that are not persisted entities.
    assert undecidable == [
        "AvailabilitySlot",
        "CancellationReceipt",
        "Error",
        "Location",
    ]


def test_slack_openapi3_contract() -> None:
    collections, pk_map, undecidable = _derive("slack_web_openapi_v2_openapi3.json")
    # Sorted by noun, so objs_teams precedes objs_team_profile_fields.
    assert collections == [
        "objs_bot_profiles",
        "objs_channels",
        "objs_comments",
        "objs_enterprise_users",
        "objs_files",
        "objs_primary_owners",
        "objs_reminders",
        "objs_teams",
        "objs_team_profile_fields",
        "teams",
    ]
    # The objs_ prefix is kept deliberately: stripping it would collide
    # objs_channel with defs_channel (see plan decision 1).
    assert [c for c in collections if not c.startswith("objs_")] == ["teams"]
    assert pk_map["teams"] == "team_id"
    assert set(pk_map[c] for c in collections if c.startswith("objs_")) == {"id"}
    assert len(undecidable) == 38


def test_slack_v2_has_no_derivable_entities() -> None:
    # This spec declares 174 operations and not one 2xx JSON object schema, so
    # it has nothing to derive from. It already fails generation today via the
    # empty-entity-set guard; this test pins that it is a pre-existing property
    # of the spec and not a regression introduced by the new rule.
    collections, pk_map, undecidable = _derive("slack_web_openapi_v2.json")
    assert collections == []
    assert pk_map == {}
    assert undecidable == []


def _rpc_spec() -> dict:
    """An RPC-shaped spec whose every operation returns a bare ``{id, name}``.

    Not a checked-in example because none of the four has this shape — which is
    exactly why the rule's behaviour on it went unnoticed — but an ordinary one:
    plenty of hand-written tool-style specs declare no ``components.schemas`` and
    return an unqualified ``id``.
    """
    thing = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
    }
    body = {"content": {"application/json": {"schema": thing}}}
    return {
        "openapi": "3.0.0",
        "info": {"title": "Thing RPC", "version": "1.0.0"},
        "paths": {
            "/things": {
                "get": {"operationId": "list_things", "responses": {"200": body}},
                "post": {"operationId": "create_thing", "responses": {"201": body}},
            },
            "/things/{id}": {
                "get": {
                    "operationId": "get_thing_details",
                    "responses": {"200": body},
                },
            },
        },
    }


def test_rpc_bare_id_responses_derive_nothing_and_go_to_the_fallback() -> None:
    """A bare ``id`` on the synthetic path must not coin operation-id collections.

    ``noun_for("id", name)`` falls back to the schema name, and on this path the
    name is a generated operation id. Deriving here would produce the collections
    ``create_things``/``get_thing_details``/``list_things`` — three fragments of
    one entity, each tagged ``"derived"`` as though the rule had decided it, and
    each an operation id leaking into the runtime contract. The rule must decline
    instead and let the scoped fallback, which sees every operation at once, name
    the entity under an honest ``"llm"`` provenance tag.
    """
    spec_dict = _rpc_spec()
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
    assert sources.synthetic is True
    assert sorted(sources.identity) == [
        "create_thing",
        "get_thing_details",
        "list_things",
    ]

    model = derive_identity(sources.identity, synthetic=True)
    assert model.collections == []
    assert model.pk_map == {}
    # In sources.identity, so the orchestrator's leftovers lookup resolves them.
    assert model.undecidable == (
        "create_thing",
        "get_thing_details",
        "list_things",
    )


def test_rpc_named_path_still_keys_a_bare_id_by_the_schema_name() -> None:
    """The named path is untouched: there the name is a spec-declared type.

    Same three schemas, reached through ``components.schemas`` instead of through
    operation responses, must still derive.
    """
    thing = {
        "type": "object",
        "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
    }
    model = derive_identity({"Thing": thing}, synthetic=False)
    assert model.collections == ["things"]
    assert model.pk_map == {"things": "id"}
    assert model.undecidable == ()


@pytest.mark.parametrize(
    "filename",
    [
        "tau2_retail_openapi.json",
        "tau2_airline_openapi.json",
        "reservation-service_openapi.json",
        "slack_web_openapi_v2_openapi3.json",
    ],
)
def test_derivation_is_stable_across_repeated_calls(filename: str) -> None:
    assert _derive(filename) == _derive(filename)


def test_synthetic_carve_out_is_load_bearing_on_tau2_retail() -> None:
    """Rule 1.4 is why tau2-retail resolves at all.

    Re-deriving the same identity map with ``synthetic=False`` disables rule 1.4.
    The measured result is 2 collections and 10 undecidable schemas, against 6 and
    6 with it. If this test starts passing with equal numbers, rule 1.4 has been
    made unconditional and the named-schema over-merge guard is now dead.
    """
    spec_dict = json.loads((EXAMPLES / "tau2_retail_openapi.json").read_text())
    sources = collect_sources(OpenAPISpec(spec_dict), spec_dict)
    assert sources.synthetic is True

    with_rule = derive_identity(sources.identity, synthetic=True)
    without = derive_identity(sources.identity, synthetic=False)

    assert len(with_rule.entities) == 6
    assert len(with_rule.undecidable) == 6
    assert without.collections == ["items", "orders"]
    assert len(without.undecidable) == 10
