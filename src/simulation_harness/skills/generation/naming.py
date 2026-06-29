"""Frontmatter name forcing for generated SKILL.md (dependency-free)."""

from __future__ import annotations

import re

# Leading YAML frontmatter block: opening `---`, body, closing `---`.
_FRONTMATTER_RE = re.compile(r"(?s)\A(---[ \t]*\n)(.*?)(\n---[ \t]*(?:\n|\Z))")
# A top-level (unindented) `name:` key within the frontmatter body.
_NAME_LINE_RE = re.compile(r"(?m)^name[ \t]*:.*$")

# Agent Skills specification: a skill name is 1-64 characters of lowercase
# alphanumeric and single hyphens, with no leading, trailing, or consecutive
# hyphens (https://agentskills.io/specification). deepagents validates this and
# warns on violation, so generated skill names are sanitized to comply.
_MAX_SKILL_NAME_LEN = 64
# Runs of one or more hyphens, used to collapse consecutive separators.
_HYPHEN_RUN_RE = re.compile(r"-+")


def sanitize_skill_name(raw: str) -> str:
    """Sanitize an arbitrary name into a valid Agent Skills skill name.

    Lowercases the input, replaces every character outside lowercase
    alphanumeric with a hyphen, collapses runs of hyphens, trims leading and
    trailing hyphens, and caps the length at 64. Falls back to ``"simulation"``
    if nothing valid remains (empty input, or input made entirely of invalid
    characters such as ``.`` or ``/``).

    Args:
        raw: The proposed name (e.g. a simulation name or OpenAPI title).

    Returns:
        A non-empty name satisfying the Agent Skills specification.
    """
    candidate = "".join(
        c if ((c.isalpha() and c.islower()) or c.isdigit()) else "-"
        for c in (raw or "").lower()
    )
    candidate = _HYPHEN_RUN_RE.sub("-", candidate).strip("-")
    candidate = candidate[:_MAX_SKILL_NAME_LEN].strip("-")
    return candidate or "simulation"


def _force_skill_name(skill_md: str, name: str) -> str:
    """Force the SKILL.md frontmatter ``name`` to equal ``name``."""
    name_line = f"name: {name}"
    match = _FRONTMATTER_RE.match(skill_md)
    if match is None:
        return f"---\n{name_line}\n---\n\n{skill_md}"
    head, body, tail = match.group(1), match.group(2), match.group(3)
    if _NAME_LINE_RE.search(body):
        body = _NAME_LINE_RE.sub(name_line, body, count=1)
    else:
        body = f"{name_line}\n{body}" if body else name_line
    return f"{head}{body}{tail}{skill_md[match.end() :]}"
