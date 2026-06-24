"""Tests for the per-simulation skill-sources helper.

The runtime ``FilesystemBackend`` uses ``virtual_mode=True``, which resolves
every requested path and rejects anything that escapes the backend root. So the
helper cannot root the backend at a throwaway dir and symlink back to the real
skill directory (the resolved target would fall outside the root), and it must
not nest the source inside the skill directory pointing back at its own parent
(the old ``.skills/<name> -> ..`` design, which created a self-referential
cycle). Instead it stages a *copy* of the skill in a fresh directory that holds
only this one skill, and roots the backend there.
"""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def staging_roots():
    """Collect staging roots created during a test and remove them on teardown."""
    roots: list[str] = []
    yield roots
    for root in roots:
        shutil.rmtree(root, ignore_errors=True)


def _make_skill_dir(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "petstore"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: petstore\ndescription: Simulate the Pet Store API.\n---\n"
        "# Pet Store\nSee [schema.json](schema.json).\n"
    )
    # Sibling files SKILL.md references via relative links must travel with it.
    (skill_dir / "schema.json").write_text('{"entities": {}}')
    (skill_dir / "db.json").write_text('{"seed": []}')
    return skill_dir


def _build(skill_dir: Path, staging_roots: list[str]) -> tuple[str, list[str]]:
    from simulation_harness.agent.skill_backend import build_skill_sources

    root_dir, sources = build_skill_sources(skill_dir)
    staging_roots.append(root_dir)
    return root_dir, sources


def test_sources_point_at_dot_skills(tmp_path, staging_roots):
    skill_dir = _make_skill_dir(tmp_path)
    _root, sources = _build(skill_dir, staging_roots)
    assert sources == ["/.skills/"]


def test_staging_root_is_outside_skill_dir(tmp_path, staging_roots):
    skill_dir = _make_skill_dir(tmp_path)
    root_dir, _ = _build(skill_dir, staging_roots)
    root = Path(root_dir).resolve()
    assert root != skill_dir.resolve()
    assert not root.is_relative_to(skill_dir.resolve())


def test_does_not_pollute_skill_dir(tmp_path, staging_roots):
    """Regression: the old design created ``skill_dir/.skills/<name> -> ..``,
    a self-referential directory cycle. The skill directory must be left
    untouched."""
    skill_dir = _make_skill_dir(tmp_path)
    _build(skill_dir, staging_roots)
    assert not (skill_dir / ".skills").exists()


def test_skill_files_are_copied_under_staging(tmp_path, staging_roots):
    skill_dir = _make_skill_dir(tmp_path)
    root_dir, _ = _build(skill_dir, staging_roots)
    staged = Path(root_dir) / ".skills" / "petstore"
    assert (staged / "SKILL.md").read_text() == (skill_dir / "SKILL.md").read_text()
    # Referenced siblings come along so progressive disclosure still resolves.
    assert (staged / "schema.json").read_text() == (skill_dir / "schema.json").read_text()
    assert (staged / "db.json").exists()


def test_staged_files_are_real_copies_not_symlinks(tmp_path, staging_roots):
    """virtual_mode rejects symlink targets outside the root, so the staged
    entries must be real files, not links back to the source."""
    skill_dir = _make_skill_dir(tmp_path)
    root_dir, _ = _build(skill_dir, staging_roots)
    staged = Path(root_dir) / ".skills" / "petstore"
    assert not staged.is_symlink()
    assert not (staged / "SKILL.md").is_symlink()


def test_stale_dot_skills_in_source_is_not_propagated(tmp_path, staging_roots):
    """A leftover ``.skills`` from the old design must not be copied into the
    staging tree (which would re-introduce the nesting)."""
    skill_dir = _make_skill_dir(tmp_path)
    (skill_dir / ".skills").mkdir()
    (skill_dir / ".skills" / "junk").write_text("stale")
    root_dir, _ = _build(skill_dir, staging_roots)
    staged = Path(root_dir) / ".skills" / "petstore"
    assert not (staged / ".skills").exists()


def test_each_call_creates_independent_staging(tmp_path, staging_roots):
    skill_dir = _make_skill_dir(tmp_path)
    root_a, _ = _build(skill_dir, staging_roots)
    root_b, _ = _build(skill_dir, staging_roots)
    assert root_a != root_b
