from unittest.mock import AsyncMock, patch

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages import seed as SD

GOOD_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"features": {"type": "array", "items": {"$ref": "#/$defs/Feature"}}},
    "$defs": {
        "Feature": {
            "type": "object",
            "additionalProperties": False,
            "x-primary-key": "id",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        }
    },
}


def _ir() -> SpecModel:
    return SpecModel(
        api_name="Aha",
        slug="aha",
        entities=[
            Entity(
                name="Feature",
                collection="features",
                primary_key="id",
                fields=[Field(name="id", type="string", required=True)],
            )
        ],
        operations=[],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


def test_validate_accepts_consistent_pair() -> None:
    assert SD.validate_schema_and_db(GOOD_SCHEMA, {"features": [{"id": "f1"}]}) == []


def test_validate_flags_db_not_matching_schema() -> None:
    errs = SD.validate_schema_and_db(GOOD_SCHEMA, {"features": [{"id": 123}]})
    assert errs


async def test_generate_seed_returns_validated_db() -> None:
    db = {"features": [{"id": "f1"}, {"id": "f2"}]}
    with patch.object(
        SD, "call_json", AsyncMock(return_value={"db_json": db})
    ) as mock_call:
        result = await SD.generate_seed(
            _ir(),
            GOOD_SCHEMA,
            [{"title": "t", "intent": "i", "operations": []}],
            llm=object(),
            retries=2,
        )
    assert result == db
    # scenarios block is included in the user prompt when non-empty
    user_prompt = mock_call.call_args.args[2]
    assert "scenarios" in user_prompt


async def test_generate_seed_omits_scenarios_block_when_empty() -> None:
    db = {"features": [{"id": "f1"}]}
    with patch.object(
        SD, "call_json", AsyncMock(return_value={"db_json": db})
    ) as mock_call:
        await SD.generate_seed(_ir(), GOOD_SCHEMA, [], llm=object(), retries=2)
    user_prompt = mock_call.call_args.args[2]
    assert "# scenarios" not in user_prompt


# --- Fix round 1, Fix 2 --------------------------------------------------
# state/loader.py takes the runtime collection set from db.json's own keys,
# not from the schema. enforce_contract (schema.py) now stamps the schema's
# top-level 'required' to store_metadata.collections and 'additionalProperties'
# to False, so the schema that reaches this stage's own validate_schema_and_db
# call catches drift in *either* direction between the IR and db.json.

ENFORCED_SCHEMA = {
    **GOOD_SCHEMA,
    "required": ["features"],
    "additionalProperties": False,
}


def test_validate_schema_and_db_catches_a_collection_missing_from_db() -> None:
    errs = SD.validate_schema_and_db(ENFORCED_SCHEMA, {})
    assert errs


def test_validate_schema_and_db_catches_an_off_contract_collection_in_db() -> None:
    errs = SD.validate_schema_and_db(
        ENFORCED_SCHEMA, {"features": [{"id": "f1"}], "ghosts": [{"id": "g1"}]}
    )
    assert errs
