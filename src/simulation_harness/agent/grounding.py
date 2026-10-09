"""Closed-world grounding check for strict-fidelity responses.

In strict mode the store is the complete truth, so every string a response
carries should be traceable to evidence: the thread's store, the request's
arguments, or the bundle's static text (spec + SKILL.md). This module finds the
strings that are not.

It is biased toward false negatives — an invented value that happens to equal
some stored string passes — because under ``enforce`` a false positive fails a
legitimate call.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

# Shortest store/request string used as a template fragment. Shorter ones ("a",
# "1") occur inside almost anything and would let every string pass.
_MIN_FRAGMENT_LEN = 3

_ISO_8601 = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
_PUNCTUATION_ONLY = re.compile(r"^[\W_]*$")
_HOLE = "\x00"

# The harness's own error envelope ({"error": "<free text>"}, defined in
# simulator_system.jinja2). Its text is written by the model, not copied from
# data, so checking it would flag every legitimate not-found error.
_ERROR_ENVELOPE_PATH = "$.error"


@dataclass(frozen=True)
class Ungrounded:
    """One response string with no evidence behind it."""

    path: str
    value: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "value": self.value}


def collect_strings(value: Any) -> set[str]:
    """Every string *value* (never a key) anywhere inside ``value``."""
    found: set[str] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.add(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


def static_evidence(api_spec: dict[str, Any], skill_md: str) -> str:
    """The bundle's static text: every string in the spec, plus SKILL.md.

    Strings are pulled from the parsed spec rather than its raw JSON so escaping
    (``\\"``, ``\\u2014``) cannot hide a verbatim match.
    """
    return "\n".join([*sorted(collect_strings(api_spec)), skill_md])


def _string_leaves(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _string_leaves(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _string_leaves(child, f"{path}[{index}]")


def _grounded(
    value: str, dynamic: set[str], fragments: list[str], static_text: str
) -> bool:
    # Exact or enum/constant match.
    if value in dynamic or value in static_text:
        return True
    # Derived substring: "ap-south-1" from "ap-south-1a".
    if any(value in evidence for evidence in dynamic):
        return True
    # Template residue: cut out every store/request fragment; what remains must
    # be punctuation or text the spec/skill states verbatim.
    residue = value
    for fragment in fragments:
        residue = residue.replace(fragment, _HOLE)
    if residue == value:
        return False
    return all(
        _PUNCTUATION_ONLY.match(segment) or segment in static_text
        for segment in residue.split(_HOLE)
    )


def check_grounding(
    response: Any,
    request_args: dict[str, Any],
    store_snapshot: dict[str, list[dict[str, Any]]],
    static_text: str,
) -> list[Ungrounded]:
    """Return the response's string leaves that no evidence accounts for.

    Not checked: object keys (fixed by schema), numbers/booleans/null (computed
    by Derivation Rules), empty strings, ISO-8601 dates/datetimes (legitimate
    "now" timestamps), and the top-level error envelope's text.
    """
    dynamic = collect_strings(store_snapshot) | collect_strings(request_args)
    fragments = sorted(
        (s for s in dynamic if len(s) >= _MIN_FRAGMENT_LEN), key=len, reverse=True
    )
    ungrounded: list[Ungrounded] = []
    for path, value in _string_leaves(response, "$"):
        if not value or path == _ERROR_ENVELOPE_PATH or _ISO_8601.match(value):
            continue
        if not _grounded(value, dynamic, fragments, static_text):
            ungrounded.append(Ungrounded(path, value))
    return ungrounded
