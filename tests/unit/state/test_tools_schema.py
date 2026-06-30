"""Test JSON Schema generation for state tools.

This test verifies that the Pydantic models used for state tools
generate valid JSON schemas that are compatible with Azure OpenAI.
"""

import json

from simulation_harness.state.tools import StateListArgs


def test_state_list_args_schema_valid() -> None:
    """Test that StateListArgs generates a valid JSON schema.

    Azure OpenAI requires that array schemas have an 'items' field.
    This test verifies that the 'sort' parameter generates a valid schema.
    """
    # Get the JSON schema
    schema = StateListArgs.model_json_schema()

    print("Generated schema:")
    print(json.dumps(schema, indent=2))

    # Check that sort property exists
    assert "sort" in schema["properties"]

    sort_schema = schema["properties"]["sort"]

    # If sort has anyOf (for optional), check each variant
    if "anyOf" in sort_schema:
        for variant in sort_schema["anyOf"]:
            if variant.get("type") == "array":
                # Array schemas MUST have 'items'
                assert "items" in variant, f"Array schema missing 'items': {variant}"

                # If items is also an array (for nested lists), it must have items too
                if variant["items"].get("type") == "array":
                    assert "items" in variant["items"], (
                        f"Nested array schema missing 'items': {variant['items']}"
                    )
                    # Verify it doesn't use prefixItems (tuple-style)
                    assert "prefixItems" not in variant["items"], (
                        f"Schema uses prefixItems (tuple-style) which Azure OpenAI rejects: {variant['items']}"
                    )

    # If sort is directly an array
    elif sort_schema.get("type") == "array":
        assert "items" in sort_schema, f"Array schema missing 'items': {sort_schema}"


def test_state_list_args_instantiation() -> None:
    """Test that StateListArgs can be instantiated with sort parameter."""
    # Test with list of lists (as LLM would provide)
    args = StateListArgs(
        store="restaurants", sort=[["name", "asc"], ["rating", "desc"]]
    )

    assert args.store == "restaurants"
    assert args.sort == [["name", "asc"], ["rating", "desc"]]

    # Test serialization
    data = args.model_dump()
    assert data["sort"] == [["name", "asc"], ["rating", "desc"]]


def test_state_list_args_from_json() -> None:
    """Test that StateListArgs can be created from JSON (as LLM would provide)."""
    # LLMs will provide lists
    json_data = {"store": "restaurants", "sort": [["name", "asc"], ["rating", "desc"]]}

    args = StateListArgs(**json_data)
    assert args.store == "restaurants"
    assert args.sort == [["name", "asc"], ["rating", "desc"]]


# Made with Bob
