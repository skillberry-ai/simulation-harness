"""Assemble a per-simulation skills root for the runtime filesystem backend.

The deepagents SkillsMiddleware discovers skills by scanning a *source*
directory for child directories that each contain a SKILL.md. There is one
active simulation per process, but the skills folder accumulates many, so we
cannot point a source at the whole skills folder (it would expose every past
simulation). Instead we build a per-simulation `.skills/` directory whose sole
child is a symlink back to this simulation's own skill directory. The backend
is rooted at the skill directory, so only this simulation's skill is visible.
"""

from pathlib import Path


def build_skill_sources(skill_dir: Path) -> tuple[str, list[str]]:
    """Create the per-simulation skills root and return backend root + sources.

    Creates ``<skill_dir>/.skills/<skill_dir.name>`` as a symlink pointing back
    to ``skill_dir`` (target ``".."``, relative to the ``.skills/`` directory),
    so that the skill's SKILL.md and its sibling schema.json/db.json all resolve
    under one backend root with no data duplication.

    Args:
        skill_dir: The simulation's skill directory (contains SKILL.md).

    Returns:
        A tuple ``(root_dir, sources)`` where ``root_dir`` is ``str(skill_dir)``
        for ``FilesystemBackend(root_dir=...)`` and ``sources`` is
        ``["/.skills/"]`` for ``SkillsMiddleware(sources=...)``.

    Note:
        Symlinks are used to avoid duplicating/​drifting the skill files. If a
        deployment target cannot symlink, this is the single place to switch to
        copying the SKILL.md instead.
    """
    skills_root = skill_dir / ".skills"
    skills_root.mkdir(parents=True, exist_ok=True)

    link = skills_root / skill_dir.name
    if not link.is_symlink():
        # Target is relative to the symlink's own directory (.skills/), so
        # ".." resolves to skill_dir.
        link.symlink_to("..", target_is_directory=True)

    return str(skill_dir), ["/.skills/"]
