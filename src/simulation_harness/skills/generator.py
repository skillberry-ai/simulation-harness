"""Skill generator - creates simulation skills from OpenAPI specs."""

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

try:
    from importlib.resources import files
except ImportError:
    from importlib_resources import files  # type: ignore[import-not-found]

import jsonschema
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI


def _load_generation_guide() -> str:
    """Load the generation guide from package assets."""
    assets = files("simulation_harness.skills.assets")
    guide_file = assets / "generate_simulator_guide.md"
    return guide_file.read_text()


def _load_system_prompt() -> str:
    """Load the system prompt from package assets."""
    assets = files("simulation_harness.skills.assets")
    prompt_file = assets / "skill_generator_prompt.md"
    return prompt_file.read_text()


class SkillGenerator:
    """Generate simulation skill files from OpenAPI specifications."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        temperature: float = 0.0,
        max_tokens: int = 20000,
        base_url: str | None = None,
    ) -> None:
        """Initialize the skill generator.

        Args:
            api_key: OpenAI API key
            model: Model to use for generation
            temperature: Temperature for response generation
            max_tokens: Maximum tokens in response
            base_url: Optional base URL for API
        """
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.base_url = base_url

    def _initialize_llm(self) -> ChatOpenAI:
        """Initialize the LLM client."""
        llm_kwargs: dict[str, Any] = {
            "model": self.model,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "model_kwargs": {"response_format": {"type": "json_object"}},
        }

        if self.base_url:
            llm_kwargs["base_url"] = self.base_url

        return ChatOpenAI(**llm_kwargs)

    async def generate_skill(
        self,
        openapi_spec: dict[str, Any],
        simulation_name: str,
        skills_folder: Path,
    ) -> Path:
        """Generate a skill from an OpenAPI specification.

        Uses atomic write pattern:
        1. Create temp dir: <skills_folder>/.<name>.tmp-<uuid>/
        2. Generate skill content via LLM (3-file JSON output)
        3. Write SKILL.md, schema.json, db.json to temp dir
        4. Validate db.json against schema.json
        5. Atomic rename: temp dir → <skills_folder>/<name>/
        6. On failure: clean up temp dir

        Args:
            openapi_spec: OpenAPI specification dictionary
            simulation_name: Name for the simulation
            skills_folder: Directory to create skill in

        Returns:
            Path to the generated SKILL.md file

        Raises:
            RuntimeError: If skill generation fails (wraps original exception)
        """
        # Create temp directory for atomic write
        temp_dir_name = f".{simulation_name}.tmp-{uuid.uuid4().hex[:8]}"
        temp_dir = skills_folder / temp_dir_name
        final_dir = skills_folder / simulation_name
        skill_file = final_dir / "SKILL.md"

        try:
            # Create temp directory
            temp_dir.mkdir(parents=True, exist_ok=True)

            # Initialize LLM
            llm = self._initialize_llm()

            # Load assets
            generation_guide = _load_generation_guide()
            system_prompt = _load_system_prompt()

            # Prepare OpenAPI spec as JSON
            openapi_json = json.dumps(openapi_spec, indent=2)

            # Prepare messages for LLM
            user_prompt = f"""Generate a complete skill package (SKILL.md, schema.json, db.json) for the API defined in the following OpenAPI specification.

Follow the instructions in the generation guide below exactly.

# Generation Guide

{generation_guide}

# OpenAPI Specification

```json
{openapi_json}
```

# Instructions

Create a complete skill package following the structure and guidelines in the generation guide.
Your response must be a single JSON object with three fields: skill_md, schema_json, and db_json.
Do not include any explanations or commentary outside the JSON object.
"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            # Generate skill files
            response = await llm.ainvoke(messages)
            response_content = str(response.content)

            # Parse JSON response
            try:
                parsed = json.loads(response_content)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"LLM response is not valid JSON: {e}"
                ) from e

            # Validate response structure
            if not isinstance(parsed, dict):
                raise RuntimeError(
                    f"LLM response must be a JSON object, got {type(parsed)}"
                )

            required_fields = ["skill_md", "schema_json", "db_json"]
            missing_fields = [f for f in required_fields if f not in parsed]
            if missing_fields:
                raise RuntimeError(
                    f"LLM response missing required fields: {missing_fields}"
                )

            # Extract components
            skill_md = parsed["skill_md"]
            schema_json = parsed["schema_json"]
            db_json = parsed["db_json"]

            # Validate types
            if not isinstance(skill_md, str):
                raise RuntimeError(
                    f"skill_md must be a string, got {type(skill_md)}"
                )
            if not isinstance(schema_json, dict):
                raise RuntimeError(
                    f"schema_json must be an object, got {type(schema_json)}"
                )
            if not isinstance(db_json, dict):
                raise RuntimeError(
                    f"db_json must be an object, got {type(db_json)}"
                )

            # Validate db.json against schema.json
            try:
                jsonschema.validate(instance=db_json, schema=schema_json)
            except jsonschema.ValidationError as e:
                raise RuntimeError(
                    f"db.json does not validate against schema.json: {e.message}"
                ) from e
            except jsonschema.SchemaError as e:
                raise RuntimeError(
                    f"schema.json is not a valid JSON Schema: {e.message}"
                ) from e

            # Write files to temp directory
            temp_skill_file = temp_dir / "SKILL.md"
            temp_schema_file = temp_dir / "schema.json"
            temp_db_file = temp_dir / "db.json"

            temp_skill_file.write_text(skill_md)
            temp_schema_file.write_text(json.dumps(schema_json, indent=2))
            temp_db_file.write_text(json.dumps(db_json, indent=2))

            # Atomic rename: temp dir → final dir
            try:
                temp_dir.rename(final_dir)
            except FileExistsError:
                # If final_dir exists, remove it and retry
                shutil.rmtree(final_dir)
                temp_dir.rename(final_dir)

            return skill_file

        except Exception as e:
            # Clean up temp directory on failure
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            # Re-raise with context
            raise RuntimeError(
                f"Skill generation failed for '{simulation_name}'"
            ) from e

# Made with Bob
