"""Frontmatter name forcing for generated SKILL.md (dependency-free)."""

from __future__ import annotations

import re

# Leading YAML frontmatter block: opening `---`, body, closing `---`.
_FRONTMATTER_RE = re.compile(r"(?s)\A(---[ \t]*\n)(.*?)(\n---[ \t]*(?:\n|\Z))")
# A top-level (unindented) `name:` key within the frontmatter body.
_NAME_LINE_RE = re.compile(r"(?m)^name[ \t]*:.*$")


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
