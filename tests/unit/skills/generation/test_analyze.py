from unittest.mock import AsyncMock, patch

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.stages import analyze as A

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Aha", "version": "1.0"},
    "paths": {
        "/features/{id}": {
            "get": {
                "operationId": "getFeature",
                "tags": ["Features"],
                "summary": "Get a feature",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


def test_extract_operations_pulls_stub_fields():
    ops = A.extract_operations(OpenAPISpec(SPEC))
    assert ops == [
        {
            "operation_id": "getFeature",
            "method": "GET",
            "path": "/features/{id}",
            "tag": "Features",
            "summary": "Get a feature",
        }
    ]


async def test_analyze_merges_enrichment_into_ir():
    enrichment = {
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
        "operation_semantics": [
            {
                "operation_id": "getFeature",
                "entity": "Feature",
                "kind": "read",
                "patterns": ["crud"],
            }
        ],
    }
    with patch.object(A, "call_json", AsyncMock(return_value=enrichment)):
        ir = await A.analyze(SPEC, slug="aha", llm=object(), retries=2)
    assert ir.slug == "aha"
    assert ir.operations[0].operation_id == "getFeature"
    assert ir.operations[0].kind.value == "read"
    assert ir.operations[0].path == "/features/{id}"  # mechanical fact preserved
    assert ir.validate_consistency() == []
