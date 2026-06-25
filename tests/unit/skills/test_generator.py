"""Tests for skill generator (delegates to the multi-step pipeline)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from simulation_harness.skills import generator as G
from simulation_harness.skills.generator import SkillGenerator
from simulation_harness.skills.generation.pipeline import SkillBundle

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Aha", "version": "1"},
    "paths": {
        "/features/{id}": {
            "get": {
                "operationId": "getFeature",
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}
BUNDLE = SkillBundle(
    skill_md="---\nname: aha\n---\n# Aha Simulation\n### /features/{id} GET\nok",
    schema={
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {},
    },
    db={"features": []},
)


class TestSkillGeneratorInitialization:
    """Test SkillGenerator initialization."""

    def test_generator_initialization(self) -> None:
        """Test that generator initializes with correct parameters."""
        api_key = SecretStr("test-api-key")
        generator = SkillGenerator(
            api_key=api_key,
            model="gpt-4",
            temperature=0.0,
            max_tokens=20000,
            base_url="https://api.openai.com/v1",
        )

        assert generator.api_key == api_key
        assert generator.model == "gpt-4"
        assert generator.temperature == 0.0
        assert generator.max_tokens == 20000
        assert generator.base_url == "https://api.openai.com/v1"

    def test_generator_initialization_with_defaults(self) -> None:
        """Test that generator uses default values when not provided."""
        from simulation_harness.config.models import GenerationConfig

        gen = SkillGenerator(api_key=SecretStr("test-api-key"))
        assert isinstance(gen.generation_config, GenerationConfig)


class TestPipelineDelegation:
    """generate_skill delegates content generation to run_pipeline."""

    async def test_generate_skill_writes_four_files_from_bundle(
        self, tmp_path: Path
    ) -> None:
        gen = SkillGenerator(api_key=SecretStr("k"))
        with patch.object(G, "run_pipeline", AsyncMock(return_value=BUNDLE)):
            result = await gen.generate_skill(SPEC, "aha", tmp_path)
        skill_dir = tmp_path / "aha"
        assert result == skill_dir / "SKILL.md"
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "schema.json").exists()
        assert (skill_dir / "db.json").exists()
        assert json.loads((skill_dir / "api.json").read_text()) == SPEC
        assert "name: aha" in (skill_dir / "SKILL.md").read_text()

    async def test_generate_skill_cleans_temp_dir_on_failure(
        self, tmp_path: Path
    ) -> None:
        gen = SkillGenerator(api_key=SecretStr("k"))
        with patch.object(
            G, "run_pipeline", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            with pytest.raises(RuntimeError):
                await gen.generate_skill(SPEC, "aha", tmp_path)
        assert list(tmp_path.glob(".aha.tmp-*")) == []
        assert not (tmp_path / "aha").exists()

    async def test_generate_skill_passes_progress_cb(self, tmp_path: Path) -> None:
        gen = SkillGenerator(api_key=SecretStr("k"))
        seen = {}

        async def fake_pipeline(spec, slug, **kwargs):
            seen["cb"] = kwargs.get("progress_cb")
            return BUNDLE

        def cb(p):
            return None

        with patch.object(G, "run_pipeline", fake_pipeline):
            await gen.generate_skill(SPEC, "aha", tmp_path, progress_cb=cb)
        assert seen["cb"] is cb


class TestBaseURLWiring:
    """Test that base_url is properly wired from config to SkillGenerator."""

    def test_skill_generator_receives_base_url_from_secrets(self) -> None:
        """Test that SkillGenerator is initialized with base_url from secrets."""
        from unittest.mock import MagicMock, patch

        import simulation_harness.api.dependencies as deps
        from simulation_harness.config.models import (
            HarnessConfig,
            LLMConfig,
            MCPConfig,
            SessionsConfig,
            SkillsConfig,
            TransportType,
        )

        config = HarnessConfig(
            llm=LLMConfig(
                provider="openai",
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
        mock_secrets = MagicMock()
        mock_secrets.llm_api_key = SecretStr("test-key")
        mock_secrets.llm_api_base = "https://custom.api.com/v1"

        with (
            patch(
                "simulation_harness.api.dependencies.get_config", return_value=config
            ),
            patch(
                "simulation_harness.api.dependencies.get_secrets",
                return_value=mock_secrets,
            ),
        ):
            deps._skill_registry = None
            registry = deps.get_skill_registry()

            assert registry.generator.base_url == "https://custom.api.com/v1"
            assert registry.generator.api_key == SecretStr("test-key")
            assert registry.generator.model == "gpt-4"

    def test_skill_generator_base_url_none_when_not_in_secrets(self) -> None:
        """Test that SkillGenerator base_url is None when not configured."""
        from unittest.mock import MagicMock, patch

        import simulation_harness.api.dependencies as deps
        from simulation_harness.config.models import (
            HarnessConfig,
            LLMConfig,
            MCPConfig,
            SessionsConfig,
            SkillsConfig,
            TransportType,
        )

        config = HarnessConfig(
            llm=LLMConfig(
                provider="openai",
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
        mock_secrets = MagicMock()
        mock_secrets.llm_api_key = SecretStr("test-key")
        mock_secrets.llm_api_base = None

        with (
            patch(
                "simulation_harness.api.dependencies.get_config", return_value=config
            ),
            patch(
                "simulation_harness.api.dependencies.get_secrets",
                return_value=mock_secrets,
            ),
        ):
            deps._skill_registry = None
            registry = deps.get_skill_registry()
            assert registry.generator.base_url is None


class TestSkillRegistryInvalidation:
    def test_load_secrets_clears_skill_registry(self, monkeypatch):
        """load_secrets() must clear the cached _skill_registry."""
        import simulation_harness.api.dependencies as deps
        from unittest.mock import MagicMock

        monkeypatch.setenv("LLM_API_KEY", "sk-first")
        monkeypatch.delenv("LLM_API_BASE", raising=False)

        from simulation_harness.config import load_secrets

        deps._skill_registry = MagicMock()
        load_secrets(env_file=None)
        assert deps._skill_registry is None

    def test_reset_skill_registry_clears_cached_singleton(self):
        """reset_skill_registry() provides a public API to clear the cache."""
        import simulation_harness.api.dependencies as deps
        from unittest.mock import MagicMock

        from simulation_harness.api.dependencies import reset_skill_registry

        deps._skill_registry = MagicMock()
        reset_skill_registry()
        assert deps._skill_registry is None


class TestForceSkillName:
    """The SKILL.md frontmatter name must match the skill directory name.

    The helper is re-exported from generator.py for backward compatibility; its
    definition now lives in skills.generation.naming.
    """

    def test_replaces_mismatched_name(self):
        from simulation_harness.skills.generator import _force_skill_name

        skill_md = (
            "---\nname: widget-simulation\n"
            "description: Simulate the Widget API.\n---\n\n# Widget\n"
        )
        out = _force_skill_name(skill_md, "widget-api")
        assert "name: widget-api" in out
        assert "widget-simulation" not in out

    def test_preserves_other_frontmatter_and_body(self):
        from simulation_harness.skills.generator import _force_skill_name

        skill_md = (
            "---\nname: widget-simulation\n"
            "description: Simulate the Widget API.\n---\n\n# Widget\n\nBody.\n"
        )
        out = _force_skill_name(skill_md, "widget-api")
        assert "description: Simulate the Widget API." in out
        assert "# Widget" in out
        assert "Body." in out

    def test_inserts_name_when_absent_from_frontmatter(self):
        from simulation_harness.skills.generator import _force_skill_name

        skill_md = "---\ndescription: Simulate the Widget API.\n---\n\n# Widget\n"
        out = _force_skill_name(skill_md, "widget-api")
        assert "name: widget-api" in out
        assert "description: Simulate the Widget API." in out

    def test_adds_frontmatter_when_missing(self):
        from simulation_harness.skills.generator import _force_skill_name

        skill_md = "# Widget\n\nNo frontmatter here.\n"
        out = _force_skill_name(skill_md, "widget-api")
        assert out.startswith("---\nname: widget-api\n---\n")
        assert "No frontmatter here." in out

    def test_only_first_name_in_frontmatter_is_rewritten(self):
        """A `name:` mention in the body must not be touched."""
        from simulation_harness.skills.generator import _force_skill_name

        skill_md = (
            "---\nname: widget-simulation\n---\n\n"
            "# Widget\n\nThe `name:` field identifies the entity.\n"
        )
        out = _force_skill_name(skill_md, "widget-api")
        assert "name: widget-api" in out
        assert "The `name:` field identifies the entity." in out
