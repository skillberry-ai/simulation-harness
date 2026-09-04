"""Provenance manifest for a generated skill bundle.

Records what produced a bundle — harness version, model, canonical input-spec
digest, generation timestamp — plus a sha256 digest and byte size for each
sibling artifact.

The purpose is reproducibility and debugging, not integrity: the digests are a
snapshot of the bytes as generated and nothing re-verifies them. In particular
``db.json`` is legitimately rewritten post-generation via
``PUT /api/v1/simulation/database``, so its digest is expected to drift.

See docs/superpowers/specs/2026-07-30-skill-provenance-manifest-design.md.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = "manifest.json"
MANIFEST_VERSION = 1

# Artifacts a manifest may describe, in the order they appear in `files`.
# manifest.json is absent by construction: it cannot digest itself.
# Keep in sync with `_BUNDLE_FILES` in core/skill_registry.py: that list is the
# authority on what belongs to a bundle, this one on what the manifest digests.
_SUBJECTS = (
    "SKILL.md",
    "schema.json",
    "db.json",
    "api.json",
    "scenarios.json",
)


def canonical_spec_digest(openapi_spec: dict[str, Any]) -> str:
    """Return the lowercase hex sha256 of the spec in canonical form.

    Serializing with sorted keys and no whitespace makes the digest independent
    of the indentation and key order the spec happened to arrive with, so the
    same logical spec always digests alike. That is what lets a reader ask "was
    this generated from the same spec?" across differently formatted
    submissions.

    This *approximates* RFC 8785 (JSON Canonicalization Scheme) but is **not** a
    conformant JCS implementation — it differs on number formatting and unicode
    escaping. That is acceptable because only this module produces and compares
    these digests; do not treat the value as interoperable with other tooling.
    """
    canonical = json.dumps(openapi_spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _rfc3339_utc(moment: datetime) -> str:
    """Format as RFC 3339 UTC with a trailing 'Z' and second precision.

    A tz-naive ``moment`` is treated as already UTC rather than passed to
    ``astimezone``, which would instead interpret it as *local* time and
    silently shift it by the host's UTC offset. Manifest generation must
    never fail or raise here, so we normalize instead of rejecting naive
    input; today's only caller passes an aware UTC datetime, but a future
    caller passing e.g. ``datetime.utcnow()`` must not get a silently wrong
    ``generatedAt``.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_entry(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "size": len(data),
        "digest": {"sha256": hashlib.sha256(data).hexdigest()},
    }


def _source_openapi(openapi_spec: dict[str, Any]) -> dict[str, Any]:
    """Describe the input spec. Absent or malformed `info` is tolerated."""
    source: dict[str, Any] = {}
    info = openapi_spec.get("info")
    if isinstance(info, dict):
        if isinstance(info.get("title"), str):
            source["title"] = info["title"]
        if isinstance(info.get("version"), str):
            source["version"] = info["version"]
    source["canonicalDigest"] = {"sha256": canonical_spec_digest(openapi_spec)}
    return source


def build_manifest(
    artifact_dir: Path,
    *,
    skill_name: str,
    openapi_spec: dict[str, Any],
    model: str,
    harness_version: str,
    generated_at: datetime,
    identity_provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the provenance manifest for the artifacts in ``artifact_dir``.

    Digests are read from the bytes on disk rather than re-serialized from
    in-memory values, so they always describe exactly what was written. The
    caller is expected to have written the sibling artifacts first — that is
    why digests come off disk rather than in-memory content. Any subject file
    (see ``_SUBJECTS``) that is absent from ``artifact_dir`` is simply omitted
    from the returned ``files`` map rather than causing an error.

    ``generated_at`` is a parameter rather than a clock read inside the function
    so callers and tests control the timestamp.

    Returns the manifest as a plain dict; the caller serializes and writes it.
    """
    return {
        "manifestVersion": MANIFEST_VERSION,
        "skill": {
            "name": skill_name,
            "generatedAt": _rfc3339_utc(generated_at),
        },
        "generator": {
            "harnessVersion": harness_version,
            "model": model,
        },
        "source": {"openapi": _source_openapi(openapi_spec)},
        # Which entities got their identity from the deterministic rule and
        # which from the LLM fallback. The fallback is still non-deterministic,
        # so a contract that depended on it must be visible in the artifact.
        "identity": {"provenance": dict(sorted((identity_provenance or {}).items()))},
        "files": {
            name: _file_entry(artifact_dir / name)
            for name in _SUBJECTS
            if (artifact_dir / name).exists()
        },
    }
