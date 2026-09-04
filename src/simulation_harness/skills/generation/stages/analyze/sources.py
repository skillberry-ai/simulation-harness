"""Selects and shapes the schema maps the analyze stage reasons over.

Two maps, on purpose:

``identity``
    What the deterministic rule may look at. For a spec with declared
    ``components.schemas`` that is the components map. For an RPC/tool-style
    spec it is **success response schemas only**, keyed by operation id — a
    request body is a *projection* of an entity (a create body legitimately
    omits the server-assigned id) and feeding it to the identity rule produces
    undecidable noise, not entities.

``enrich``
    What the LLM may look at: requests *and* responses, value-deduplicated.
    Request bodies carry field-level prose responses omit, and tau2-style specs
    repeat one entity shape across a dozen operations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from simulation_harness.openapi.parser import OpenAPISpec


@dataclass(frozen=True)
class SchemaSources:
    synthetic: bool
    identity: dict[str, dict]
    enrich: dict[str, dict]


def _unwrap_returns(resp: dict) -> dict:
    """Unwrap the tool-style ``{"returns": {...}}`` response envelope one level.

    For tool-driven specs, success responses carry a {"properties": {"returns":
    {...}}} wrapper; this extracts the inner schema.
    """
    props = resp.get("properties") if isinstance(resp, dict) else None
    if isinstance(props, dict) and isinstance(props.get("returns"), dict):
        return props["returns"]
    return resp


def dedup_by_value(schemas: dict[str, dict]) -> dict[str, dict]:
    """Drop keys whose schema is structurally identical to an earlier one.

    Iterates sorted names so the surviving key is a function of the content,
    not of how the input map happened to be built.
    """
    seen: set[str] = set()
    out: dict[str, dict] = {}
    for name in sorted(schemas):
        fingerprint = json.dumps(schemas[name], sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out[name] = schemas[name]
    return out


def inline_schema_evidence(spec: OpenAPISpec) -> dict:
    """Synthesize a `name -> JSON schema` map from operation request/response
    bodies, for RPC/tool-style specs that declare no `components.schemas`.

    The output mirrors the shape of `components.schemas` so it can be fed to
    the extract stage unchanged. Keys are suffixed `__request`/`__response`.
    The tool-style ``{"returns": {...}}`` response envelope is unwrapped one
    level so the LLM sees the entity shape directly.
    """
    evidence: dict = {}
    for op in spec.operations:
        req = op.get_request_schema()
        if req:
            evidence[f"{op.operation_id}__request"] = req
        resp = op.get_success_response_schema()
        if resp:
            resp = _unwrap_returns(resp)
            evidence[f"{op.operation_id}__response"] = resp
    return evidence


def _identity_responses(spec: OpenAPISpec) -> dict[str, dict]:
    """Success-response object schemas, keyed by operation id."""
    out: dict[str, dict] = {}
    for op in spec.operations:
        resp = op.get_success_response_schema()
        if not isinstance(resp, dict):
            continue
        resp = _unwrap_returns(resp)
        props = resp.get("properties")
        if resp.get("type") == "object" and isinstance(props, dict) and props:
            out[op.operation_id] = resp
    return out


def collect_sources(spec: OpenAPISpec, spec_dict: dict) -> SchemaSources:
    components = spec_dict.get("components", {}).get("schemas", {}) or {}
    if components:
        return SchemaSources(
            synthetic=False,
            identity=dict(components),
            enrich=dict(components),
        )
    return SchemaSources(
        synthetic=True,
        identity=_identity_responses(spec),
        enrich=dedup_by_value(inline_schema_evidence(spec)),
    )
