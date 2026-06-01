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
        2. Generate skill content via LLM
        3. Write SKILL.md to temp dir
        4. Atomic rename: temp dir → <skills_folder>/<name>/
        5. On failure: clean up temp dir

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
            user_prompt = f"""Generate a complete SKILL.md file for the API defined in the following OpenAPI specification.

Follow the instructions in the generation guide below exactly.

# Generation Guide

{generation_guide}

# OpenAPI Specification

```json
{openapi_json}
```

# Instructions

Create a complete SKILL.md file following the structure and guidelines in the generation guide.
Generate ONLY the SKILL.md content. Do not include any explanations or commentary outside the file content.
Start directly with the YAML frontmatter (---) and end with the last line of the markdown content.
"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]

            # Generate skill file
            response = await llm.ainvoke(messages)
            skill_content = str(response.content)

            # Write to temp directory
            temp_skill_file = temp_dir / "SKILL.md"
            temp_skill_file.write_text(skill_content)

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
