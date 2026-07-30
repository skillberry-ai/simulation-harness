"""Tests that generate_skill() emits a provenance manifest."""

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from simulation_harness import __version__
from simulation_harness.skills import generator as G
from simulation_harness.skills.generation.pipeline import SkillBundle
from simulation_harness.skills.generator import SkillGenerator

BUNDLE = SkillBundle(
    skill_md="---\nname: demo\n---\n# Demo\n",
    schema={"type": "object", "properties": {}},
    db={"items": []},
)
BUNDLE_WITH_SCENARIOS = SkillBundle(
    skill_md="---\nname: demo\n---\n# Demo\n",
    schema={"type": "object", "properties": {}},
    db={"items": []},
    scenarios=[{"name": "happy path"}],
)

SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Demo API", "version": "1.2.0"},
    "paths": {},
}

API_KEY = "sk-not-a-real-key-abc123"


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "skills"
    folder.mkdir()
    return folder


async def _generate(skills_dir: Path, bundle: SkillBundle) -> Path:
    generator = SkillGenerator(api_key=SecretStr(API_KEY), model="gpt-4o-mini")
    with patch.object(G, "run_pipeline", AsyncMock(return_value=bundle)):
        await generator.generate_skill(
            openapi_spec=SPEC,
            simulation_name="demo",
            skills_folder=skills_dir,
        )
    return skills_dir / "demo"


def _manifest(skill_dir: Path) -> dict[str, Any]:
    return json.loads((skill_dir / "manifest.json").read_text())


async def test_generate_skill_writes_manifest(skills_dir: Path) -> None:
    skill_dir = await _generate(skills_dir, BUNDLE)

    manifest = _manifest(skill_dir)
    assert manifest["manifestVersion"] == 1
    assert manifest["skill"]["name"] == "demo"
    assert manifest["generator"] == {
        "harnessVersion": __version__,
        "model": "gpt-4o-mini",
    }
    assert manifest["source"]["openapi"]["title"] == "Demo API"


async def test_manifest_digests_match_files_on_disk(skills_dir: Path) -> None:
    """The whole point: digests describe the bytes actually written."""
    skill_dir = await _generate(skills_dir, BUNDLE)

    files = _manifest(skill_dir)["files"]
    assert set(files) == {"SKILL.md", "schema.json", "db.json", "api.json"}
    for name, entry in files.items():
        data = (skill_dir / name).read_bytes()
        assert entry["digest"]["sha256"] == hashlib.sha256(data).hexdigest(), name
        assert entry["size"] == len(data), name


async def test_manifest_includes_scenarios_when_generated(skills_dir: Path) -> None:
    skill_dir = await _generate(skills_dir, BUNDLE_WITH_SCENARIOS)

    files = _manifest(skill_dir)["files"]
    data = (skill_dir / "scenarios.json").read_bytes()
    assert (
        files["scenarios.json"]["digest"]["sha256"] == hashlib.sha256(data).hexdigest()
    )


async def test_manifest_contains_no_secret_material(skills_dir: Path) -> None:
    skill_dir = await _generate(skills_dir, BUNDLE)

    raw = (skill_dir / "manifest.json").read_text()
    assert API_KEY not in raw
    assert "SecretStr" not in raw
    assert "base_url" not in raw and "baseUrl" not in raw


async def test_generated_at_is_rfc3339_utc(skills_dir: Path) -> None:
    from datetime import datetime

    skill_dir = await _generate(skills_dir, BUNDLE)

    stamp = _manifest(skill_dir)["skill"]["generatedAt"]
    assert stamp.endswith("Z")
    datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")  # raises if malformed


async def test_no_manifest_left_behind_on_failure(skills_dir: Path) -> None:
    generator = SkillGenerator(api_key=SecretStr(API_KEY))
    with patch.object(G, "run_pipeline", AsyncMock(side_effect=RuntimeError("boom"))):
        with pytest.raises(RuntimeError, match="Skill generation failed"):
            await generator.generate_skill(
                openapi_spec=SPEC,
                simulation_name="demo",
                skills_folder=skills_dir,
            )

    assert not (skills_dir / "demo").exists()
    assert [d for d in skills_dir.iterdir() if d.name.startswith(".")] == []
