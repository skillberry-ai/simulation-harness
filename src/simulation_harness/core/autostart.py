"""Resolve which baked skill (if any) to auto-start on server boot."""

from __future__ import annotations

from simulation_harness.core.skill_registry import SkillRegistry
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)


class AutostartConfigError(Exception):
    """An explicit autostart name was configured but has no complete artifacts."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Configured autostart simulation '{name}' has no complete artifacts."
        )


def resolve_autostart_target(
    enabled: bool, configured: str | None, registry: SkillRegistry
) -> str | None:
    """Return the skill name to auto-start, or None to boot idle.

    Precedence:
      0. Autostart disabled → None (wins over an explicit name).
      1. Explicit name → that skill, or AutostartConfigError if incomplete.
      2. No name: 0 skills → None; 1 skill → it; >1 → most recent (+ WARNING).
    """
    if not enabled:
        logger.info("Autostart disabled by config; booting idle.")
        return None

    if configured:
        if registry.is_complete(configured):
            return configured
        raise AutostartConfigError(configured)

    complete = registry.list_complete_skills()
    if not complete:
        logger.info("Autostart: no complete skills found; booting idle.")
        return None
    if len(complete) == 1:
        return complete[0]

    chosen = registry.most_recent_complete_skill()
    skipped = [s for s in complete if s != chosen]
    logger.warning(
        "Autostart: multiple complete skills %s; starting most recent '%s', skipping %s.",
        complete,
        chosen,
        skipped,
    )
    return chosen
