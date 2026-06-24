"""Tests for the per-simulation skill-sources helper."""

from pathlib import Path

from simulation_harness.agent.skill_backend import build_skill_sources


def _make_skill_dir(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "petstore"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: petstore\ndescription: Simulate the Pet Store API.\n---\n# Pet Store\n"
    )
    return skill_dir


def test_returns_root_and_sources(tmp_path):
    skill_dir = _make_skill_dir(tmp_path)
    root_dir, sources = build_skill_sources(skill_dir)
    assert root_dir == str(skill_dir)
    assert sources == ["/.skills/"]


def test_creates_symlink_named_after_skill_dir(tmp_path):
    skill_dir = _make_skill_dir(tmp_path)
    build_skill_sources(skill_dir)
    link = skill_dir / ".skills" / "petstore"
    assert link.is_symlink()


def test_symlink_resolves_to_skill_files(tmp_path):
    skill_dir = _make_skill_dir(tmp_path)
    build_skill_sources(skill_dir)
    linked_skill_md = skill_dir / ".skills" / "petstore" / "SKILL.md"
    assert linked_skill_md.resolve() == (skill_dir / "SKILL.md").resolve()


def test_idempotent(tmp_path):
    skill_dir = _make_skill_dir(tmp_path)
    build_skill_sources(skill_dir)
    # second call must not raise and must leave exactly one entry
    build_skill_sources(skill_dir)
    entries = list((skill_dir / ".skills").iterdir())
    assert len(entries) == 1
    assert entries[0].is_symlink()
