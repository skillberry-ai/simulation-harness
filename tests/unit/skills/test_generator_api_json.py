"""Tests for storing OpenAPI spec as api.json in skill directory."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from simulation_harness.skills import generator as G
from simulation_harness.skills.generator import SkillGenerator
from simulation_harness.skills.generation.pipeline import SkillBundle

BUNDLE = SkillBundle(
    skill_md="---\nname: test-simulation\n---\n# Test\n",
    schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {},
    },
    db={"items": []},
)


class TestApiJsonStorage:
    """Test that OpenAPI spec is stored as api.json."""

    @pytest.fixture
    def temp_skills_dir(self, tmp_path: Path) -> Path:
        """Create a temporary skills directory."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        return skills_dir

    @pytest.fixture
    def sample_openapi_spec(self) -> dict[str, Any]:
        """Create a sample OpenAPI spec."""
        return {
            "openapi": "3.0.0",
            "info": {
                "title": "Test API",
                "version": "1.0.0",
            },
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "getTest",
                        "summary": "Get test data",
                        "responses": {"200": {"description": "Success"}},
                    }
                }
            },
        }

    @pytest.mark.asyncio
    async def test_generate_skill_creates_api_json(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that generate_skill creates api.json file matching the spec."""
        generator = SkillGenerator(api_key=SecretStr("test-key"))

        with patch.object(G, "run_pipeline", AsyncMock(return_value=BUNDLE)):
            await generator.generate_skill(
                openapi_spec=sample_openapi_spec,
                simulation_name="test-simulation",
                skills_folder=temp_skills_dir,
            )

        skill_dir = temp_skills_dir / "test-simulation"
        api_json_path = skill_dir / "api.json"
        assert api_json_path.exists(), "api.json file should be created"
        assert json.loads(api_json_path.read_text()) == sample_openapi_spec

    @pytest.mark.asyncio
    async def test_api_json_is_valid_json_format(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that api.json is always in JSON format."""
        generator = SkillGenerator(api_key=SecretStr("test-key"))

        with patch.object(G, "run_pipeline", AsyncMock(return_value=BUNDLE)):
            await generator.generate_skill(
                openapi_spec=sample_openapi_spec,
                simulation_name="test-simulation",
                skills_folder=temp_skills_dir,
            )

        skill_dir = temp_skills_dir / "test-simulation"
        api_json_content = json.loads((skill_dir / "api.json").read_text())
        assert isinstance(api_json_content, dict)
        assert api_json_content["openapi"] == "3.0.0"

    @pytest.mark.asyncio
    async def test_api_json_cleanup_on_failure(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that api.json is cleaned up if skill generation fails."""
        generator = SkillGenerator(api_key=SecretStr("test-key"))

        with patch.object(
            G, "run_pipeline", AsyncMock(side_effect=RuntimeError("pipeline error"))
        ):
            with pytest.raises(
                RuntimeError, match="Skill generation failed for 'test-simulation'"
            ):
                await generator.generate_skill(
                    openapi_spec=sample_openapi_spec,
                    simulation_name="test-simulation",
                    skills_folder=temp_skills_dir,
                )

        skill_dir = temp_skills_dir / "test-simulation"
        assert not skill_dir.exists(), "Skill directory should not exist after failure"
        temp_dirs = [d for d in temp_skills_dir.iterdir() if d.name.startswith(".")]
        assert len(temp_dirs) == 0, f"Temp directories not cleaned up: {temp_dirs}"

    @pytest.mark.asyncio
    async def test_api_json_with_complex_spec(
        self,
        temp_skills_dir: Path,
    ) -> None:
        """Test that api.json preserves complex OpenAPI spec structure."""
        generator = SkillGenerator(api_key=SecretStr("test-key"))

        complex_spec = {
            "openapi": "3.0.0",
            "info": {
                "title": "Complex API",
                "version": "2.0.0",
                "description": "A complex API with many features",
            },
            "servers": [
                {"url": "https://api.example.com/v1"},
                {"url": "https://staging.example.com/v1"},
            ],
            "security": [{"bearerAuth": []}],
            "components": {
                "securitySchemes": {
                    "bearerAuth": {
                        "type": "http",
                        "scheme": "bearer",
                    }
                },
                "schemas": {
                    "User": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "email": {"type": "string", "format": "email"},
                        },
                    }
                },
            },
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "responses": {"200": {"description": "Success"}},
                    }
                }
            },
        }

        with patch.object(G, "run_pipeline", AsyncMock(return_value=BUNDLE)):
            await generator.generate_skill(
                openapi_spec=complex_spec,
                simulation_name="test-simulation",
                skills_folder=temp_skills_dir,
            )

        skill_dir = temp_skills_dir / "test-simulation"
        api_json_content = json.loads((skill_dir / "api.json").read_text())

        assert api_json_content == complex_spec
        assert "servers" in api_json_content
        assert len(api_json_content["servers"]) == 2
        assert "security" in api_json_content
        assert "components" in api_json_content
