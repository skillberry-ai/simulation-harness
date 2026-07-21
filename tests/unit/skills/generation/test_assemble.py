from simulation_harness.skills.generation.ir import (
    Entity,
    Field,
    Operation,
    OperationKind,
    SpecModel,
    StoreMetadata,
)
from simulation_harness.skills.generation.stages import assemble as A

SCHEMA = {
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
        operations=[
            Operation(
                operation_id="getFeature",
                method="GET",
                path="/features/{id}",
                entity="Feature",
                kind=OperationKind.read,
            )
        ],
        store_metadata=StoreMetadata(
            collections=["features"], pk_map={"features": "id"}
        ),
    )


def test_render_preamble_has_frontmatter_and_sections() -> None:
    md = A.render_preamble(_ir(), [])
    assert md.startswith("---")
    assert "name: aha" in md
    assert "## Session State Management" in md
    assert "schema.json" in md and "db.json" in md


def test_assemble_forces_name_and_appends_sections() -> None:
    ir = _ir()
    md = A.assemble_skill(ir, A.render_preamble(ir, []), ["### /features/{id} GET\nok"])
    assert "name: aha" in md
    assert "### /features/{id} GET" in md


def test_validate_bundle_passes_for_complete_skill() -> None:
    ir = _ir()
    md = A.assemble_skill(ir, A.render_preamble(ir, []), ["### /features/{id} GET\nok"])
    assert A.validate_bundle(ir, md, SCHEMA, {"features": [{"id": "f1"}]}) == []


def test_validate_bundle_flags_missing_operation_section() -> None:
    ir = _ir()
    md = A.assemble_skill(ir, A.render_preamble(ir, []), [])  # no sections
    errs = A.validate_bundle(ir, md, SCHEMA, {"features": [{"id": "f1"}]})
    assert any("getFeature" in e or "/features/{id} GET" in e for e in errs)


def test_render_preamble_includes_scenarios_section() -> None:
    scenarios = [
        {
            "title": "Read a feature",
            "intent": "Fetch a feature by id.",
            "operations": ["getFeature"],
        }
    ]
    out = A.render_preamble(_ir(), scenarios)
    assert "## Example Scenarios" in out
    assert "Read a feature" in out
    assert "getFeature" in out


def test_render_preamble_omits_scenarios_section_when_empty() -> None:
    out = A.render_preamble(_ir(), [])
    assert "## Example Scenarios" not in out


def test_render_preamble_includes_behavior_section() -> None:
    out = A.render_preamble(
        _ir(), [], behavior_section="### Derivation Rules\n- total = sum"
    )
    assert "### Derivation Rules" in out
    assert "- total = sum" in out


def test_render_preamble_omits_behavior_when_empty() -> None:
    out = A.render_preamble(_ir(), [])
    assert "### Derivation Rules" not in out
    assert "\n\n\n" not in out
