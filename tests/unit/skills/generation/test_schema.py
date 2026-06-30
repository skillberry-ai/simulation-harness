from unittest.mock import AsyncMock, patch

from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages import schema as S

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


def test_validate_schema_accepts_valid_schema() -> None:
    assert S.validate_schema(GOOD_SCHEMA) == []


def test_validate_schema_flags_invalid_schema() -> None:
    assert S.validate_schema({"type": "not-a-type"})


async def test_generate_schema_returns_validated_schema() -> None:
    with patch.object(
        S, "call_json", AsyncMock(return_value={"schema_json": GOOD_SCHEMA})
    ):
        schema = await S.generate_schema(_ir(), llm=object(), retries=2)
    assert schema == GOOD_SCHEMA
