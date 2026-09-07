import logging
from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.skills.generation.ir import Entity, Field, StoreMetadata
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages.analyze import extract as E
from simulation_harness.skills.generation.stages.analyze.identity import (
    DerivedEntity,
    IdentityModel,
)

DERIVED = IdentityModel(
    entities=(
        DerivedEntity(
            name="Reservation",
            collection="reservations",
            primary_key="id",
            fields=(("id", "string"),),
            sources=("Reservation",),
        ),
    ),
    undecidable=("Error", "Location"),
)

VALID = {
    "api_name": "Aha",
    "entities": [
        {
            "name": "Feature",
            "collection": "features",
            "primary_key": "id",
            "fields": [{"name": "id", "type": "string", "required": True}],
        }
    ],
    "store_metadata": {"collections": ["features"], "pk_map": {"features": "id"}},
}


async def test_extract_data_model_builds_model() -> None:
    with patch.object(E, "call_json", AsyncMock(return_value=VALID)):
        dm = await E.extract_data_model({}, slug="aha", llm=object(), retries=2)
    assert dm.api_name == "Aha"
    assert dm.entities[0].name == "Feature"
    assert dm.store_metadata.pk_map == {"features": "id"}


def test_validate_data_model_flags_undeclared_collection() -> None:
    dm = E.DataModel(
        api_name="x",
        entities=[Entity(name="F", collection="features", primary_key="id", fields=[])],
        store_metadata=StoreMetadata(collections=["other"], pk_map={"other": "id"}),
    )
    errors = E.validate_data_model(dm)
    assert any("features" in e for e in errors)


async def test_extract_repairs_then_succeeds() -> None:
    # first payload omits store_metadata (shape error), second is valid
    bad = {"api_name": "Aha", "entities": []}
    seq = iter([bad, VALID])
    with patch.object(E, "call_json", AsyncMock(side_effect=lambda *a, **k: next(seq))):
        dm = await E.extract_data_model({}, slug="aha", llm=object(), retries=1)
    assert dm.entities[0].name == "Feature"


async def test_extract_exhausts_retries_raises() -> None:
    bad = {"api_name": "Aha", "entities": []}  # missing store_metadata every time
    with patch.object(E, "call_json", AsyncMock(return_value=bad)):
        with pytest.raises(GenerationStageError) as exc:
            await E.extract_data_model({}, slug="aha", llm=object(), retries=1)
    assert exc.value.stage == "extract"


async def test_fallback_may_decline_every_schema() -> None:
    payload = {
        "api_name": "Res",
        "entities": [],
        "store_metadata": {"collections": [], "pk_map": {}},
        "declined": ["Error", "Location"],
    }
    with patch.object(E, "call_json", AsyncMock(return_value=payload)):
        dm = await E.extract_data_model(
            {"Error": {}, "Location": {}}, "res", object(), retries=0, derived=DERIVED
        )
    assert dm.entities == []
    assert dm.declined == ["Error", "Location"]


async def test_declined_schemas_are_logged_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The decline list needs a trace, and the log is the only one it gets.

    It is deliberately not in ``manifest.json`` (see ``DataModel.declined``), so
    without this line an over-eager decline shows up only as an entity missing at
    simulation time, with nothing tying it back to this stage.
    """
    payload = {
        "api_name": "Res",
        "entities": [],
        "store_metadata": {"collections": [], "pk_map": {}},
        "declined": ["Location", "Error"],
    }
    with (
        patch.object(E, "call_json", AsyncMock(return_value=payload)),
        caplog.at_level(logging.INFO, logger=E.logger.name),
    ):
        await E.extract_data_model(
            {"Error": {}, "Location": {}}, "res", object(), retries=0, derived=DERIVED
        )

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("declined 2 of 2" in m for m in messages), messages
    # Sorted, so the line does not jitter with LLM output order.
    assert any("['Error', 'Location']" in m for m in messages), messages


async def test_no_declines_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """The common case is an empty list; it must not add a line per generation."""
    with (
        patch.object(E, "call_json", AsyncMock(return_value=VALID)),
        caplog.at_level(logging.INFO, logger=E.logger.name),
    ):
        await E.extract_data_model({}, slug="aha", llm=object(), retries=0)

    assert [r for r in caplog.records if "declined" in r.getMessage()] == []


async def test_fallback_may_not_redefine_a_derived_collection() -> None:
    payload = {
        "api_name": "Res",
        "entities": [
            {
                "name": "Location",
                "collection": "reservations",
                "primary_key": "loc_id",
                "fields": [{"name": "loc_id", "type": "string", "required": True}],
            }
        ],
        "store_metadata": {
            "collections": ["reservations"],
            "pk_map": {"reservations": "loc_id"},
        },
    }
    with patch.object(E, "call_json", AsyncMock(return_value=payload)):
        with pytest.raises(GenerationStageError) as exc:
            await E.extract_data_model(
                {"Location": {}}, "res", object(), retries=0, derived=DERIVED
            )
    assert exc.value.stage == "extract"
    assert any("reservations" in e for e in exc.value.errors)


async def test_fallback_may_not_redefine_a_derived_collection_case_variant() -> None:
    payload = {
        "api_name": "Res",
        "entities": [
            {
                "name": "Location",
                "collection": "Reservations",
                "primary_key": "loc_id",
                "fields": [{"name": "loc_id", "type": "string", "required": True}],
            }
        ],
        "store_metadata": {
            "collections": ["Reservations"],
            "pk_map": {"Reservations": "loc_id"},
        },
    }
    with patch.object(E, "call_json", AsyncMock(return_value=payload)):
        with pytest.raises(GenerationStageError) as exc:
            await E.extract_data_model(
                {"Location": {}}, "res", object(), retries=0, derived=DERIVED
            )
    assert exc.value.stage == "extract"
    assert any("reservations" in e for e in exc.value.errors)


async def test_fallback_may_not_redefine_a_derived_collection_whitespace_variant() -> (
    None
):
    payload = {
        "api_name": "Res",
        "entities": [
            {
                "name": "Location",
                "collection": " reservations ",
                "primary_key": "loc_id",
                "fields": [{"name": "loc_id", "type": "string", "required": True}],
            }
        ],
        "store_metadata": {
            "collections": [" reservations "],
            "pk_map": {" reservations ": "loc_id"},
        },
    }
    with patch.object(E, "call_json", AsyncMock(return_value=payload)):
        with pytest.raises(GenerationStageError) as exc:
            await E.extract_data_model(
                {"Location": {}}, "res", object(), retries=0, derived=DERIVED
            )
    assert exc.value.stage == "extract"
    assert any("reservations" in e for e in exc.value.errors)


async def test_fallback_declined_defaults_to_empty() -> None:
    payload = {
        "api_name": "Res",
        "entities": [],
        "store_metadata": {"collections": [], "pk_map": {}},
    }
    with patch.object(E, "call_json", AsyncMock(return_value=payload)):
        dm = await E.extract_data_model({}, "res", object(), retries=0)
    assert dm.declined == []


async def test_fallback_prompt_carries_the_derived_entities_as_context() -> None:
    payload = {
        "api_name": "Res",
        "entities": [],
        "store_metadata": {"collections": [], "pk_map": {}},
    }
    call = AsyncMock(return_value=payload)
    with patch.object(E, "call_json", call):
        await E.extract_data_model(
            {"Error": {}}, "res", object(), retries=0, derived=DERIVED
        )
    assert call.await_args is not None
    user_message = call.await_args.args[2]
    assert "reservations" in user_message
    assert "Reservation" in user_message


def test_validate_data_model_flags_a_primary_key_missing_from_fields() -> None:
    """The check ``validate_enrichment`` already makes, now made here too.

    Without it this entity reaches ``validate_schema`` two stages later, where
    no repair prompt can act on it and the failure is attributed to "schema".
    """
    dm = E.DataModel(
        api_name="x",
        entities=[
            Entity(
                name="Coupon",
                collection="coupons",
                primary_key="coupon_id",
                fields=[Field(name="code", type="string", required=False)],
            )
        ],
        store_metadata=StoreMetadata(
            collections=["coupons"], pk_map={"coupons": "coupon_id"}
        ),
    )
    errors = E.validate_data_model(dm)
    assert any("coupon_id" in e and "Coupon" in e for e in errors)


def test_validate_data_model_flags_a_duplicate_collection() -> None:
    """Mirrors ``validate_enrichment``'s ``Counter`` check (enrich.py).

    Without this, a fallback payload with two entities on one collection
    validates clean, reaches ``compose_data_model``, and has both members
    dropped with only a ``logger.warning`` — the LLM is never told and never
    gets a chance to repair it.
    """
    dm = E.DataModel(
        api_name="x",
        entities=[
            Entity(
                name="ItemA",
                collection="items",
                primary_key="item_id",
                fields=[Field(name="item_id", type="string", required=True)],
            ),
            Entity(
                name="ItemB",
                collection="items",
                primary_key="sku",
                fields=[Field(name="sku", type="string", required=True)],
            ),
        ],
        store_metadata=StoreMetadata(
            collections=["items"], pk_map={"items": "item_id"}
        ),
    )
    errors = E.validate_data_model(dm)
    assert any("items" in e and "2 entities" in e for e in errors)


def test_validate_data_model_flags_a_duplicate_name() -> None:
    dm = E.DataModel(
        api_name="x",
        entities=[
            Entity(
                name="Coupon",
                collection="coupons",
                primary_key="coupon_id",
                fields=[Field(name="coupon_id", type="string", required=True)],
            ),
            Entity(
                name="Coupon",
                collection="vouchers",
                primary_key="voucher_id",
                fields=[Field(name="voucher_id", type="string", required=True)],
            ),
        ],
        store_metadata=StoreMetadata(
            collections=["coupons", "vouchers"],
            pk_map={"coupons": "coupon_id", "vouchers": "voucher_id"},
        ),
    )
    errors = E.validate_data_model(dm)
    assert any("Coupon" in e and "2 entities" in e for e in errors)


async def test_extract_data_model_repairs_a_duplicate_collection() -> None:
    """The duplicate-collection error must actually reach the repair loop.

    Not just returned by the validator in isolation — end to end, so the LLM
    sees it as feedback on the next attempt.
    """
    duplicate_collection = {
        "api_name": "Res",
        "entities": [
            {
                "name": "ItemA",
                "collection": "items",
                "primary_key": "item_id",
                "fields": [{"name": "item_id", "type": "string", "required": True}],
            },
            {
                "name": "ItemB",
                "collection": "items",
                "primary_key": "sku",
                "fields": [{"name": "sku", "type": "string", "required": True}],
            },
        ],
        "store_metadata": {"collections": ["items"], "pk_map": {"items": "item_id"}},
    }
    seq = iter([duplicate_collection, VALID])
    calls: list[str] = []

    async def fake_call_json(llm, system, user):
        calls.append(user)
        return next(seq)

    with patch.object(E, "call_json", AsyncMock(side_effect=fake_call_json)):
        dm = await E.extract_data_model({}, slug="aha", llm=object(), retries=1)
    assert dm.entities[0].name == "Feature"
    assert len(calls) == 2
    assert "claimed by 2 entities" in calls[1]


def test_validate_data_model_accepts_a_primary_key_present_in_fields() -> None:
    dm = E.DataModel(
        api_name="x",
        entities=[
            Entity(
                name="Coupon",
                collection="coupons",
                primary_key="coupon_id",
                fields=[
                    Field(name="coupon_id", type="string", required=True),
                    Field(name="code", type="string", required=False),
                ],
            )
        ],
        store_metadata=StoreMetadata(
            collections=["coupons"], pk_map={"coupons": "coupon_id"}
        ),
    )
    assert E.validate_data_model(dm) == []


# --- array-shaped leftovers ---------------------------------------------------
#
# These reach the fallback by an explicit route, not by the rule declining:
# `_identity_responses` defers an array-of-objects response because deciding one is
# outside what the deterministic rule may do. They are also the leftovers a decline
# hurts most — a listing with no collection behind it leaves its operation inventing
# results at runtime, which is how tau2-airline lost Flight and Airport.
#
# Measured on tau2-airline, 8 runs per arm, cache bypassed:
#   list_all_airports     accepted 2/8 -> 8/8   (Fisher p=0.007)
#   search_direct_flight  accepted 0/8 -> 6/8   (Fisher p=0.007)
# Every acceptance was named `Airport`/`airports`/`iata` and
# `Flight`/`flights`/`flight_number` — never `airport_codes` or `direct_flights`,
# the names the element titles and operation ids would have suggested. The four
# non-listing leftovers stayed declined in all 16 runs, so it did not trade the
# decline bias for over-acceptance.


def test_array_shaped_block_names_only_the_deferred_leftovers() -> None:
    block = E._array_shaped_context(
        frozenset({"list_all_airports", "search_direct_flight"}),
        {
            "list_all_airports": {},
            "search_direct_flight": {},
            "get_reservation_details": {},
        },
    )
    assert "Array-shaped leftovers" in block
    assert "list_all_airports" in block
    assert "search_direct_flight" in block
    assert "get_reservation_details" not in block


def test_array_shaped_block_ignores_names_not_in_this_call() -> None:
    """The fallback is scoped to the undecidable subset, so a deferred name that is
    not in `components` must not be announced as present."""
    block = E._array_shaped_context(frozenset({"absent_op"}), {"list_all_airports": {}})
    assert block == ""


def test_no_array_shaped_block_when_none_are_deferred() -> None:
    assert E._array_shaped_context(frozenset(), {"a": {}}) == ""


def test_extract_prompt_makes_declining_a_listing_the_answer_needing_a_reason() -> None:
    """The prompt otherwise says declining is expected — correct for most leftovers,
    and exactly the bias that lost these two."""
    p = " ".join(E._load_prompt().split())
    assert "Array-shaped leftovers" in p
    assert "a listing is served from somewhere" in p
    assert "declining is the answer that needs a reason" in p
    # The naming trap: element titles say `DirectFlight`/`AirportCode`, and the
    # operation id says `search_direct_flight`. All three are the wrong collection.
    assert "not after the operation or the item schema's title" in p
