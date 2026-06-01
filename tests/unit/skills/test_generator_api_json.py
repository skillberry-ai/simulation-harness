"""Tests for storing OpenAPI spec as api.json in skill directory."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from simulation_harness.skills.generator import SkillGenerator


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
                        "responses": {
                            "200": {
                                "description": "Success",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "id": {"type": "string"},
                                                "name": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            }
                        },
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
        """Test that generate_skill creates api.json file."""
        generator = SkillGenerator(api_key="test-key")
        
        # Mock the LLM response with 3-file JSON structure
        mock_response = MagicMock()
        mock_response.content = """{
  "skill_md": "---\\nname: test-simulation\\ndescription: Test simulation\\n---\\n\\n# Test Simulation\\n\\nTest content",
  "schema_json": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Test API Simulator State",
    "type": "object",
    "required": ["items"],
    "properties": {
      "items": {
        "type": "array",
        "items": {"$ref": "#/$defs/Item"}
      }
    },
    "$defs": {
      "Item": {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
          "id": {"type": "string"},
          "name": {"type": "string"}
        },
        "additionalProperties": false
      }
    }
  },
  "db_json": {
    "items": [
      {"id": "item_001", "name": "Test Item"}
    ]
  }
}"""
        
        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm
            
            result_path = await generator.generate_skill(
                openapi_spec=sample_openapi_spec,
                simulation_name="test-simulation",
                skills_folder=temp_skills_dir,
            )
        
        # Verify api.json was created
        skill_dir = temp_skills_dir / "test-simulation"
        api_json_path = skill_dir / "api.json"
        assert api_json_path.exists(), "api.json file should be created"
        
        # Verify api.json content matches input spec
        api_json_content = json.loads(api_json_path.read_text())
        assert api_json_content == sample_openapi_spec

    @pytest.mark.asyncio
    async def test_api_json_is_valid_json_format(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that api.json is always in JSON format, even if input was YAML."""
        generator = SkillGenerator(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.content = '{"skill_md": "---\\nname: test\\n---\\n# Test", "schema_json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": {"items": {"type": "array", "items": {"type": "object"}}}}, "db_json": {"items": []}}'
        
        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm
            
            await generator.generate_skill(
                openapi_spec=sample_openapi_spec,
                simulation_name="test-simulation",
                skills_folder=temp_skills_dir,
            )
        
        # Verify api.json is valid JSON
        skill_dir = temp_skills_dir / "test-simulation"
        api_json_path = skill_dir / "api.json"
        
        # Should be able to parse as JSON
        api_json_content = json.loads(api_json_path.read_text())
        assert isinstance(api_json_content, dict)
        assert api_json_content["openapi"] == "3.0.0"

    @pytest.mark.asyncio
    async def test_api_json_cleanup_on_failure(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that api.json is cleaned up if skill generation fails."""
        generator = SkillGenerator(api_key="test-key")
        
        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
            mock_llm_class.return_value = mock_llm
            
            with pytest.raises(RuntimeError, match="Skill generation failed for 'test-simulation'"):
                await generator.generate_skill(
                    openapi_spec=sample_openapi_spec,
                    simulation_name="test-simulation",
                    skills_folder=temp_skills_dir,
                )
        
        # Verify api.json was cleaned up (no temp dirs or final dir)
        skill_dir = temp_skills_dir / "test-simulation"
        assert not skill_dir.exists(), "Skill directory should not exist after failure"
        
        # Check that temp directories were cleaned up
        temp_dirs = [d for d in temp_skills_dir.iterdir() if d.name.startswith(".")]
        assert len(temp_dirs) == 0, f"Temp directories not cleaned up: {temp_dirs}"

    @pytest.mark.asyncio
    async def test_api_json_with_complex_spec(
        self,
        temp_skills_dir: Path,
    ) -> None:
        """Test that api.json preserves complex OpenAPI spec structure."""
        generator = SkillGenerator(api_key="test-key")
        
        # Complex spec with nested schemas, security, servers, etc.
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
        
        mock_response = MagicMock()
        mock_response.content = '{"skill_md": "---\\nname: test\\n---\\n# Test", "schema_json": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties": {"items": {"type": "array", "items": {"type": "object"}}}}, "db_json": {"items": []}}'
        
        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm
            
            await generator.generate_skill(
                openapi_spec=complex_spec,
                simulation_name="test-simulation",
                skills_folder=temp_skills_dir,
            )
        
        # Verify api.json preserves all structure
        skill_dir = temp_skills_dir / "test-simulation"
        api_json_path = skill_dir / "api.json"
        api_json_content = json.loads(api_json_path.read_text())
        
        assert api_json_content == complex_spec
        assert "servers" in api_json_content
        assert len(api_json_content["servers"]) == 2
        assert "security" in api_json_content
        assert "components" in api_json_content

# Made with Bob
