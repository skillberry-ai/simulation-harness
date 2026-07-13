"""Stage 1 orchestrator: spec → IR via extract → classify (fan-out) → merge."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import SpecModel
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages.analyze.classify import (
    classify_batch,
    plan_classify_batches,
)
from simulation_harness.skills.generation.stages.analyze.extract import (
    extract_data_model,
)
from simulation_harness.skills.generation.stages.analyze.merge import (
    build_spec_model,
    validate_coverage,
)

__all__ = ["analyze", "extract_operations", "inline_schema_evidence"]


def extract_operations(spec: OpenAPISpec) -> list[dict]:
    # Reuse the parser's operations so the IR's operation_ids are the same
    # sanitized, collision-free ids the MCP layer exposes as tool names.
    return [
        {
            "operation_id": op.operation_id,
            "method": op.method.upper(),
            "path": op.path,
            "tag": op.tags[0] if op.tags else None,
            "summary": op.summary or None,
        }
        for op in spec.operations
    ]


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
            props = resp.get("properties") if isinstance(resp, dict) else None
            if isinstance(props, dict) and isinstance(props.get("returns"), dict):
                resp = props["returns"]
            evidence[f"{op.operation_id}__response"] = resp
    return evidence


async def _guard(coro, timeout):
    if timeout is None:
        return await coro
    return await asyncio.wait_for(coro, timeout=timeout)


async def analyze(
    spec_dict: dict,
    slug: str,
    *,
    extract_llm,
    classify_llm,
    retries: int,
    batch_cap: int,
    concurrency: int,
    timeout: float | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> SpecModel:
    cb = progress_cb or (lambda _p: None)
    spec = OpenAPISpec(spec_dict)
    stubs = extract_operations(spec)
    components = spec_dict.get("components", {}).get("schemas", {})
    # RPC/tool-style specs declare no components.schemas; fall back to the
    # schemas carried inline in operation request/response bodies.
    schema_source = components or inline_schema_evidence(spec)

    # Stage 1a — extract data model
    cb("extracting_model")
    dm = await _guard(
        extract_data_model(schema_source, slug, extract_llm, retries=retries), timeout
    )
    if not dm.entities:
        raise GenerationStageError(
            "extract",
            [
                "no entities extracted: the spec declares no components.schemas "
                "and no usable request/response body schemas were found"
            ],
        )
    entity_names = [e.name for e in dm.entities]

    # Stage 1b — classify operation semantics (bounded fan-out)
    batches = plan_classify_batches(stubs, cap=batch_cap)
    total = len(batches)
    sem = asyncio.Semaphore(concurrency)
    done = 0
    lock = asyncio.Lock()

    async def run_batch(batch):
        nonlocal done
        async with sem:
            records = await _guard(
                classify_batch(batch, entity_names, classify_llm, retries=retries),
                timeout,
            )
        async with lock:
            done += 1
            cb(f"classifying_ops {done}/{total}")
        return records

    results = await asyncio.gather(*[run_batch(b) for b in batches])
    semantics = [record for batch in results for record in batch]

    # Merge + validate (global coverage, then IR cross-refs)
    coverage = validate_coverage(stubs, semantics)
    if coverage:
        raise GenerationStageError("classify", coverage)
    ir = build_spec_model(slug, stubs, dm, semantics)
    consistency = ir.validate_consistency()
    if consistency:
        raise GenerationStageError("analyze", consistency)
    return ir
