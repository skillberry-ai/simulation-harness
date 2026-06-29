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


def _ir():
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


def test_validate_accepts_consistent_pair():
    assert SD.validate_schema_and_db(GOOD_SCHEMA, {"features": [{"id": "f1"}]}) == []


def test_validate_flags_db_not_matching_schema():
    errs = SD.validate_schema_and_db(GOOD_SCHEMA, {"features": [{"id": 123}]})
    assert errs


async def test_generate_seed_returns_validated_db():
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


async def test_generate_seed_omits_scenarios_block_when_empty():
    db = {"features": [{"id": "f1"}]}
    with patch.object(
        SD, "call_json", AsyncMock(return_value={"db_json": db})
    ) as mock_call:
        await SD.generate_seed(_ir(), GOOD_SCHEMA, [], llm=object(), retries=2)
    user_prompt = mock_call.call_args.args[2]
    assert "# scenarios" not in user_prompt
