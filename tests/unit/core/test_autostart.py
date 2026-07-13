"""Tests for the boot-time autostart resolver."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from simulation_harness.core.autostart import (
    AutostartConfigError,
    resolve_autostart_target,
)
from simulation_harness.core.skill_registry import SkillRegistry


def _bake(folder: Path, name: str, mtime: int) -> None:
    d = folder / name
    d.mkdir(parents=True)
    for f in ("SKILL.md", "schema.json", "db.json", "api.json"):
        (d / f).write_text(json.dumps({}) if f.endswith(".json") else "# skill")
    os.utime(d / "SKILL.md", (mtime, mtime))


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    return SkillRegistry(skills_folder=tmp_path, generator=MagicMock())


def test_explicit_name_present(registry: SkillRegistry, tmp_path: Path) -> None:
    _bake(tmp_path, "acme", 1000)
    assert resolve_autostart_target(True, "acme", registry) == "acme"


def test_explicit_name_missing_raises(registry: SkillRegistry) -> None:
    with pytest.raises(AutostartConfigError):
        resolve_autostart_target(True, "ghost", registry)


def test_no_name_no_skills_returns_none(registry: SkillRegistry) -> None:
    assert resolve_autostart_target(True, None, registry) is None


def test_no_name_single_skill(registry: SkillRegistry, tmp_path: Path) -> None:
    _bake(tmp_path, "only", 1000)
    assert resolve_autostart_target(True, None, registry) == "only"


def test_no_name_multiple_picks_most_recent(
    registry: SkillRegistry, tmp_path: Path
) -> None:
    _bake(tmp_path, "old", 1000)
    _bake(tmp_path, "new", 2000)
    assert resolve_autostart_target(True, None, registry) == "new"


def test_disabled_ignores_explicit_name(
    registry: SkillRegistry, tmp_path: Path
) -> None:
    _bake(tmp_path, "acme", 1000)
    assert resolve_autostart_target(False, "acme", registry) is None


def test_disabled_ignores_discovered_skills(
    registry: SkillRegistry, tmp_path: Path
) -> None:
    _bake(tmp_path, "old", 1000)
    _bake(tmp_path, "new", 2000)
    assert resolve_autostart_target(False, None, registry) is None
