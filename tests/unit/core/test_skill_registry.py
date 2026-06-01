"""Tests for SkillRegistry."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from simulation_harness.core.skill_registry import SkillRegistry


@pytest.fixture
def temp_skills_dir(tmp_path):
    """Create a temporary skills directory."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return skills_dir


@pytest.fixture
def mock_generator():
    """Create a mock skill generator."""
    generator = MagicMock()
    generator.generate_skill = AsyncMock()
    return generator


@pytest.fixture
def sample_openapi_spec():
    """Create a sample OpenAPI spec."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {
            "/test": {
                "get": {
                    "operationId": "getTest",
                    "responses": {"200": {"description": "Success"}},
                }
            }
        },
    }


@pytest.mark.asyncio
async def test_ensure_skill_generates_new_skill(temp_skills_dir, mock_generator, sample_openapi_spec):
    """Test that ensure_skill generates a new skill when none exists."""
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    skill_path = temp_skills_dir / "test-sim" / "SKILL.md"
    mock_generator.generate_skill.return_value = skill_path
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_path
    mock_generator.generate_skill.assert_called_once_with(
        openapi_spec=sample_openapi_spec,
        simulation_name="test-sim",
        skills_folder=temp_skills_dir,
    )


@pytest.mark.asyncio
async def test_ensure_skill_reuses_existing_skill(temp_skills_dir, mock_generator, sample_openapi_spec):
    """Test that ensure_skill reuses existing skill when all 4 files exist."""
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create existing skill with all 4 files
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "schema.json").write_text('{"type": "object"}')
    (skill_dir / "db.json").write_text('{}')
    (skill_dir / "api.json").write_text('{"openapi": "3.0.0"}')
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_file
    mock_generator.generate_skill.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_skill_regenerates_when_flag_set(temp_skills_dir, mock_generator, sample_openapi_spec):
    """Test that ensure_skill regenerates when regenerate flag is set."""
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create existing complete skill
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "schema.json").write_text('{"type": "object"}')
    (skill_dir / "db.json").write_text('{}')
    (skill_dir / "api.json").write_text('{"openapi": "3.0.0"}')
    
    mock_generator.generate_skill.return_value = skill_file
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec, regenerate=True)
    
    assert result == skill_file
    mock_generator.generate_skill.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_skill_logs_warning_on_reuse(temp_skills_dir, mock_generator, sample_openapi_spec, caplog):
    """Test that ensure_skill logs warning when reusing existing skill."""
    import logging
    caplog.set_level(logging.WARNING)
    
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create existing complete skill
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "schema.json").write_text('{"type": "object"}')
    (skill_dir / "db.json").write_text('{}')
    (skill_dir / "api.json").write_text('{"openapi": "3.0.0"}')
    
    await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    # Check that warning was logged
    assert any("Reusing existing skill" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_ensure_skill_handles_generation_error(temp_skills_dir, mock_generator, sample_openapi_spec):
    """Test that ensure_skill handles generation errors."""
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    mock_generator.generate_skill.side_effect = RuntimeError("Generation failed")
    
    with pytest.raises(RuntimeError, match="Generation failed"):
        await registry.ensure_skill("test-sim", sample_openapi_spec)


@pytest.mark.asyncio
async def test_ensure_skill_logs_warning_with_regeneration_reminder(temp_skills_dir, mock_generator, sample_openapi_spec, caplog):
    """Test that ensure_skill logs warning with regeneration reminder."""
    import logging
    caplog.set_level(logging.WARNING)
    
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create existing complete skill with all 4 files
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "schema.json").write_text('{"type": "object"}')
    (skill_dir / "db.json").write_text('{}')
    (skill_dir / "api.json").write_text('{"openapi": "3.0.0"}')
    
    await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    # Check that warning includes regeneration reminder
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("regenerate=true" in msg.lower() for msg in warning_messages)


@pytest.mark.asyncio
async def test_ensure_skill_regenerates_when_schema_missing(temp_skills_dir, mock_generator, sample_openapi_spec, caplog):
    """Test that ensure_skill regenerates when schema.json is missing."""
    import logging
    caplog.set_level(logging.WARNING)
    
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create skill with only SKILL.md and db.json (schema.json missing)
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "db.json").write_text('{}')
    
    mock_generator.generate_skill.return_value = skill_file
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_file
    mock_generator.generate_skill.assert_called_once()
    
    # Check that warning was logged about missing files
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("incomplete" in msg.lower() and "schema.json" in msg for msg in warning_messages)


@pytest.mark.asyncio
async def test_ensure_skill_regenerates_when_db_missing(temp_skills_dir, mock_generator, sample_openapi_spec, caplog):
    """Test that ensure_skill regenerates when db.json is missing."""
    import logging
    caplog.set_level(logging.WARNING)
    
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create skill with only SKILL.md and schema.json (db.json missing)
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "schema.json").write_text('{"type": "object"}')
    
    mock_generator.generate_skill.return_value = skill_file
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_file
    mock_generator.generate_skill.assert_called_once()
    
    # Check that warning was logged about missing files
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("incomplete" in msg.lower() and "db.json" in msg for msg in warning_messages)


@pytest.mark.asyncio
async def test_ensure_skill_regenerates_when_all_files_missing(temp_skills_dir, mock_generator, sample_openapi_spec):
    """Test that ensure_skill regenerates when all files are missing."""
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    skill_file = temp_skills_dir / "test-sim" / "SKILL.md"
    mock_generator.generate_skill.return_value = skill_file
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_file
    mock_generator.generate_skill.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_skill_regenerates_when_multiple_files_missing(temp_skills_dir, mock_generator, sample_openapi_spec, caplog):
    """Test that ensure_skill regenerates when multiple files are missing."""
    import logging
    caplog.set_level(logging.WARNING)
    
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create skill with only SKILL.md (schema.json and db.json missing)
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    
    mock_generator.generate_skill.return_value = skill_file
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_file
    mock_generator.generate_skill.assert_called_once()
    
    # Check that warning was logged about missing files
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("incomplete" in msg.lower() for msg in warning_messages)
    # Should mention both missing files
    incomplete_msg = [msg for msg in warning_messages if "incomplete" in msg.lower()][0]
    assert "schema.json" in incomplete_msg
    assert "db.json" in incomplete_msg


@pytest.mark.asyncio
async def test_ensure_skill_does_not_regenerate_complete_skill(temp_skills_dir, mock_generator, sample_openapi_spec, caplog):
    """Test that ensure_skill does not regenerate when all 4 files exist."""
    import logging
    caplog.set_level(logging.WARNING)
    
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create complete skill with all 4 files
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "schema.json").write_text('{"type": "object"}')
    (skill_dir / "db.json").write_text('{}')
    (skill_dir / "api.json").write_text('{"openapi": "3.0.0"}')
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_file
    # Should NOT call generate_skill when all files exist
    mock_generator.generate_skill.assert_not_called()
    
    # Should log reuse warning, not incomplete warning
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert len(warning_messages) == 1
    assert "Reusing existing skill" in warning_messages[0]
    assert "incomplete" not in warning_messages[0].lower()
    assert "test-sim" in warning_messages[0]
    assert "SKILL.md modified:" in warning_messages[0]
    assert "regenerate=true" in warning_messages[0].lower() or "regenerate: true" in warning_messages[0].lower()


@pytest.mark.asyncio
async def test_ensure_skill_regenerates_when_api_json_missing(temp_skills_dir, mock_generator, sample_openapi_spec, caplog):
    """Test that ensure_skill regenerates when api.json is missing."""
    import logging
    caplog.set_level(logging.WARNING)
    
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create skill with SKILL.md, schema.json, and db.json but no api.json
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "schema.json").write_text('{"type": "object"}')
    (skill_dir / "db.json").write_text('{}')
    
    mock_generator.generate_skill.return_value = skill_file
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_file
    mock_generator.generate_skill.assert_called_once()
    
    # Check that warning was logged about missing files
    warning_messages = [record.message for record in caplog.records if record.levelname == "WARNING"]
    assert any("incomplete" in msg.lower() and "api.json" in msg for msg in warning_messages)


@pytest.mark.asyncio
async def test_ensure_skill_reuses_when_all_four_files_exist(temp_skills_dir, mock_generator, sample_openapi_spec):
    """Test that ensure_skill reuses existing skill when all 4 files exist (including api.json)."""
    registry = SkillRegistry(temp_skills_dir, mock_generator)
    
    # Create existing skill with all 4 files
    skill_dir = temp_skills_dir / "test-sim"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Existing skill")
    (skill_dir / "schema.json").write_text('{"type": "object"}')
    (skill_dir / "db.json").write_text('{}')
    (skill_dir / "api.json").write_text('{"openapi": "3.0.0"}')
    
    result = await registry.ensure_skill("test-sim", sample_openapi_spec)
    
    assert result == skill_file
    mock_generator.generate_skill.assert_not_called()

# Made with Bob