"""Tests for skill generator."""

import shutil
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from simulation_harness.skills.generator import SkillGenerator


class TestSkillGeneratorInitialization:
    """Test SkillGenerator initialization."""

    def test_generator_initialization(self) -> None:
        """Test that generator initializes with correct parameters."""
        api_key = "test-api-key"
        model = "gpt-4"
        temperature = 0.0
        max_tokens = 20000
        base_url = "https://api.openai.com/v1"

        generator = SkillGenerator(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=base_url,
        )

        assert generator.api_key == api_key
        assert generator.model == model
        assert generator.temperature == temperature
        assert generator.max_tokens == max_tokens
        assert generator.base_url == base_url

    def test_generator_initialization_with_defaults(self) -> None:
        """Test that generator uses default values when not provided."""
        api_key = "test-api-key"

        generator = SkillGenerator(api_key=api_key)


    def test_llm_initialization_with_all_parameters(self) -> None:
        """Test that LLM is initialized with correct parameters."""
        generator = SkillGenerator(
            api_key="test-key",
            model="gpt-4-turbo",
            temperature=0.5,
            max_tokens=10000,
            base_url="https://custom.api.com",
        )

        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm:
            generator._initialize_llm()

            mock_llm.assert_called_once_with(
                model="gpt-4-turbo",
                api_key="test-key",
                temperature=0.5,
                max_tokens=10000,
                base_url="https://custom.api.com",
            )

    def test_llm_initialization_without_base_url(self) -> None:
        """Test that LLM is initialized without base_url when not provided."""
        generator = SkillGenerator(api_key="test-key")

        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm:
            generator._initialize_llm()

            mock_llm.assert_called_once_with(
                model="gpt-4",
                api_key="test-key",
                temperature=0.0,
                max_tokens=20000,
            )


class TestSkillGeneration:
    """Test skill generation functionality."""

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
    async def test_generate_skill_creates_skill_file(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that generate_skill creates a SKILL.md file."""
        generator = SkillGenerator(api_key="test-key")
        
        # Mock the LLM response
        mock_response = MagicMock()
        mock_response.content = """---
name: test-simulation
description: Test simulation
---

# Test Simulation

Test content
"""
        
        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm
            
            result_path = await generator.generate_skill(
                openapi_spec=sample_openapi_spec,
                simulation_name="test-simulation",
                skills_folder=temp_skills_dir,
            )
        
        # Verify the skill file was created
        assert result_path.exists()
        assert result_path.name == "SKILL.md"
        assert result_path.parent.name == "test-simulation"
        
        # Verify content
        content = result_path.read_text()
        assert "name: test-simulation" in content
        assert "Test Simulation" in content

    @pytest.mark.asyncio
    async def test_atomic_write_no_temp_dirs_on_success(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that atomic write leaves no temp directories on success."""
        generator = SkillGenerator(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.content = "---\nname: test\n---\n# Test"
        
        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm
            
            await generator.generate_skill(
                openapi_spec=sample_openapi_spec,
                simulation_name="test-simulation",
                skills_folder=temp_skills_dir,
            )
        
        # Check for temp directories (should be none)
        temp_dirs = [d for d in temp_skills_dir.iterdir() if d.name.startswith(".")]
        assert len(temp_dirs) == 0, f"Found temp directories: {temp_dirs}"

    @pytest.mark.asyncio
    async def test_atomic_write_cleans_up_on_failure(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that atomic write cleans up temp directories on failure."""
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
        
        # Check that temp directories were cleaned up
        temp_dirs = [d for d in temp_skills_dir.iterdir() if d.name.startswith(".")]
        assert len(temp_dirs) == 0, f"Temp directories not cleaned up: {temp_dirs}"

    @pytest.mark.asyncio
    async def test_atomic_write_no_partial_files(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that no partial SKILL.md files are left on failure."""
        generator = SkillGenerator(api_key="test-key")
        
        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            # Simulate failure during LLM call
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("Write error"))
            mock_llm_class.return_value = mock_llm
            
            with pytest.raises(RuntimeError):
                await generator.generate_skill(
                    openapi_spec=sample_openapi_spec,
                    simulation_name="test-simulation",
                    skills_folder=temp_skills_dir,
                )
        
        # No SKILL.md should exist in target directory
        skill_file = temp_skills_dir / "test-simulation" / "SKILL.md"
        assert not skill_file.exists(), "Partial SKILL.md file was left behind"
        
        # Target directory should not exist at all
        target_dir = temp_skills_dir / "test-simulation"
        assert not target_dir.exists(), "Target directory was created despite failure"

    @pytest.mark.asyncio
    async def test_atomic_write_cleanup_on_write_failure(
        self,
        temp_skills_dir: Path,
        sample_openapi_spec: dict[str, Any],
    ) -> None:
        """Test that temp dir is cleaned up even if write fails after LLM call."""
        generator = SkillGenerator(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.content = "---\nname: test\n---\n# Test"
        
        with patch("simulation_harness.skills.generator.ChatOpenAI") as mock_llm_class:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_llm_class.return_value = mock_llm
            
            # Mock Path.write_text to fail
            with patch("pathlib.Path.write_text", side_effect=OSError("Disk full")):
                with pytest.raises(RuntimeError):
                    await generator.generate_skill(
                        openapi_spec=sample_openapi_spec,
                        simulation_name="test-simulation",
                        skills_folder=temp_skills_dir,
                    )
        
        # Temp dirs should be cleaned up (no .test-simulation.tmp-* directories)
        temp_dirs = list(temp_skills_dir.glob(".test-simulation.tmp-*"))
        assert len(temp_dirs) == 0, f"Found temp dirs that weren't cleaned up: {temp_dirs}"


class TestAssetLoading:
    """Test asset loading from package."""

    def test_assets_load_from_package(self) -> None:
        """Test that assets can be loaded from the package."""
        from simulation_harness.skills.generator import _load_generation_guide, _load_system_prompt
        
        # These should not raise exceptions
        guide = _load_generation_guide()
        assert len(guide) > 0
        assert "Guide: Generating" in guide or "guide" in guide.lower()
        
        prompt = _load_system_prompt()
        assert len(prompt) > 0
        assert "simulation" in prompt.lower() or "skill" in prompt.lower()


class TestBaseURLWiring:
    """Test that base_url is properly wired from config to SkillGenerator."""

    def test_skill_generator_receives_base_url_from_config(self) -> None:
        """Test that SkillGenerator is initialized with base_url from config.
        
        This test verifies the fix for the bug where get_skill_registry() was
        reading from environment variables instead of using the loaded config,
        and not passing base_url to SkillGenerator at all.
        """
        from unittest.mock import patch
        import simulation_harness.api.dependencies as deps
        from simulation_harness.config.models import HarnessConfig, LLMConfig, SkillsConfig, SessionsConfig, MCPConfig, TransportType
        
        # Create a real config with api_base set
        config = HarnessConfig(
            llm=LLMConfig(
                provider="openai",
                api_key="test-key",
                api_base="https://custom.api.com/v1",
                skill_generation_model="gpt-4",
                simulation_model="gpt-4",
                temperature=0.0,
            ),
            skills=SkillsConfig(folder="./skills"),
            sessions=SessionsConfig(
                max_messages=100,
                idle_timeout_seconds=3600,
            ),
            mcp=MCPConfig(transport=TransportType.SSE),
        )
        
        # Patch get_config where it's imported in dependencies module
        with patch("simulation_harness.api.dependencies.get_config", return_value=config):
            # Reset the global registry to force recreation
            deps._skill_registry = None
            
            # Get the registry (which should create SkillGenerator with base_url)
            registry = deps.get_skill_registry()
            
            # Verify the generator was created with the correct base_url
            assert registry.generator.base_url == "https://custom.api.com/v1"
            assert registry.generator.api_key == "test-key"
            assert registry.generator.model == "gpt-4"

    def test_skill_generator_base_url_none_when_not_in_config(self) -> None:
        """Test that SkillGenerator base_url is None when not configured."""
        from unittest.mock import patch
        import simulation_harness.api.dependencies as deps
        from simulation_harness.config.models import HarnessConfig, LLMConfig, SkillsConfig, SessionsConfig, MCPConfig, TransportType
        
        # Create a real config without api_base
        config = HarnessConfig(
            llm=LLMConfig(
                provider="openai",
                api_key="test-key",
                api_base=None,
                skill_generation_model="gpt-4",
                simulation_model="gpt-4",
                temperature=0.0,
            ),
            skills=SkillsConfig(folder="./skills"),
            sessions=SessionsConfig(
                max_messages=100,
                idle_timeout_seconds=3600,
            ),
            mcp=MCPConfig(transport=TransportType.SSE),
        )
        
        # Patch get_config where it's imported in dependencies module
        with patch("simulation_harness.api.dependencies.get_config", return_value=config):
            # Reset the global registry
            deps._skill_registry = None
            
            # Get the registry
            registry = deps.get_skill_registry()
            
            # Verify base_url is None (will use OpenAI default)
            assert registry.generator.base_url is None

    def test_skill_generator_falls_back_to_env_vars_when_config_not_loaded(self) -> None:
        """Test that SkillGenerator falls back to environment variables when config not loaded."""
        from unittest.mock import patch
        import simulation_harness.api.dependencies as deps
        
        # Mock get_config to raise RuntimeError (config not loaded)
        with patch("simulation_harness.api.dependencies.get_config", side_effect=RuntimeError("Configuration not loaded")):
            # Mock environment variables
            with patch.dict("os.environ", {
                "SKILLS_FOLDER": "/tmp/test-skills",
                "OPENAI_API_KEY": "env-api-key",
                "SKILL_GENERATOR_MODEL": "gpt-3.5-turbo",
                "OPENAI_API_BASE": "https://env.api.com/v1",
            }):
                # Reset the global registry
                deps._skill_registry = None
                
                # Get the registry (should fall back to env vars)
                registry = deps.get_skill_registry()
                
                # Verify the generator was created with env var values
                assert registry.generator.base_url == "https://env.api.com/v1"
                assert registry.generator.api_key == "env-api-key"
                assert registry.generator.model == "gpt-3.5-turbo"
                assert str(registry.skills_folder) == "/tmp/test-skills"
