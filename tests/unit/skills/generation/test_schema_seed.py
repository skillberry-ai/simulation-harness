from unittest.mock import AsyncMock, patch

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages import schema_seed as S

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
    assert S.validate_schema_and_db(GOOD_SCHEMA, {"features": [{"id": "f1"}]}) == []


def test_validate_flags_db_not_matching_schema():
    errs = S.validate_schema_and_db(GOOD_SCHEMA, {"features": [{"id": 123}]})
    assert errs and any("123" in e or "integer" in e or "string" in e for e in errs)


def test_validate_flags_invalid_schema():
    errs = S.validate_schema_and_db({"type": "not-a-type"}, {})
    assert errs


async def test_generate_returns_validated_pair():
    payload = {"schema_json": GOOD_SCHEMA, "db_json": {"features": [{"id": "f1"}]}}
    with patch.object(S, "call_json", AsyncMock(return_value=payload)):
        schema, db = await S.generate_schema_and_seed(_ir(), llm=object(), retries=2)
    assert schema == GOOD_SCHEMA
    assert db == {"features": [{"id": "f1"}]}
