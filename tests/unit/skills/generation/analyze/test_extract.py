from unittest.mock import AsyncMock, patch

import pytest

from simulation_harness.skills.generation.ir import Entity, StoreMetadata
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
