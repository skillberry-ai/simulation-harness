"""Assemble a per-simulation skills root for the runtime filesystem backend.

The deepagents SkillsMiddleware discovers skills by scanning a *source*
directory for child directories that each contain a SKILL.md. There is one
active simulation per process, but the skills folder accumulates many, so we
cannot point a source at the whole skills folder (it would expose every past
simulation).

The runtime ``FilesystemBackend`` runs with ``virtual_mode=True``, which
resolves every requested path (following symlinks) and rejects anything that
escapes the backend root. That constrains the layout in two ways:

* We cannot root the backend at a throwaway directory and symlink back to the
  real skill directory — the resolved target would fall outside the root and be
  rejected.
* We must not nest the source *inside* the skill directory and point it back at
  its own parent. The previous design did exactly that with a
  ``<skill_dir>/.skills/<name> -> ..`` symlink, which left a self-referential
  directory cycle inside the published skill directory.

So we stage a *copy* of the skill in a fresh, throwaway directory that holds
nothing but this one skill, and root the backend there::

    <staging>/                       # backend root (created per simulation)
    └── .skills/
        └── <name>/                  # a copy of the skill directory
            ├── SKILL.md
            ├── schema.json
            └── ...

Copying (rather than symlinking) is required by ``virtual_mode``. It does not
risk drift: the staged files are read-only at runtime — mutable session state
flows through the StoreRegistry against the *original* skill directory, never
through this backend — and the staging directory is rebuilt for each
simulation. The caller owns the staging directory and must remove it when the
simulation ends (see ``DeepAgent.shutdown``).

``manifest.json`` is excluded from the copy: it is build provenance with no
value to the simulating agent, and the agent's readable surface is kept to the
artifacts it actually uses.
"""

import shutil
import tempfile
from pathlib import Path


def build_skill_sources(skill_dir: Path) -> tuple[str, list[str]]:
    """Stage ``skill_dir`` in a fresh root and return backend root + sources.

    Creates a new temporary directory and copies ``skill_dir`` into
    ``<staging>/.skills/<skill_dir.name>``. The backend is rooted at
    ``<staging>``, so the SkillsMiddleware discovers exactly this one skill and
    no sibling simulations leak in.

    A stale ``.skills`` directory left inside ``skill_dir`` by the old design is
    skipped during the copy, so it is never propagated into the staging tree.

    Args:
        skill_dir: The simulation's skill directory (contains SKILL.md).

    Returns:
        A tuple ``(root_dir, sources)`` where ``root_dir`` is the staging
        directory for ``FilesystemBackend(root_dir=...)`` and ``sources`` is
        ``["/.skills/"]`` for ``SkillsMiddleware(sources=...)``.

        The caller owns ``root_dir`` and must remove it (e.g. on agent
        shutdown) once the simulation ends.
    """
    staging = Path(tempfile.mkdtemp(prefix="skill-sources-"))
    dest = staging / ".skills" / skill_dir.name
    shutil.copytree(
        skill_dir,
        dest,
        ignore=shutil.ignore_patterns(".skills", "manifest.json"),
    )
    return str(staging), ["/.skills/"]
