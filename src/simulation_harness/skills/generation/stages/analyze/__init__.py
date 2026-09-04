"""Stage 1 orchestrator: spec → IR via extract → classify (fan-out) → merge."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import OperationEvidence, SpecModel
from simulation_harness.skills.generation.repair import (
    GenerationStageError,
    guard_timeout,
)
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
from simulation_harness.skills.generation.stages.analyze.sources import (
    collect_sources,
    inline_schema_evidence,
)

__all__ = [
    "analyze",
    "collect_sources",
    "extract_operation_evidence",
    "extract_operations",
    "inline_schema_evidence",
]


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


def extract_operation_evidence(spec: OpenAPISpec) -> dict[str, OperationEvidence]:
    """Build the sparse ``operation_id -> OperationEvidence`` map for the IR.

    Kept separate from :func:`extract_operations` on purpose. The stub dicts that
    function returns are dumped wholesale into the classify prompt
    (``classify_batch``), and classify is a shape-only consumer — bucketing needs
    shape, contracts need intent. Evidence must not ride on the stubs.

    Normalization lives here so every consumer inherits it identically:

    - ``description`` is stripped; empty becomes ``None``. The parser defaults an
      absent description to ``""``, so this is load-bearing.
    - A description equal to the operation's ``summary`` after stripping is
      dropped as redundant — the summary already reaches every consumer. True of
      6 of 16 tau2-retail operations and 13 of 14 tau2-airline ones.
    - A non-``str`` description (some specs put an object there) is dropped
      rather than raised on. This runs before any LLM call, so raising would
      abort generation on a spec that otherwise parses fine.
    - An operation with no surviving evidence gets **no key**, keeping the map
      sparse and :meth:`SpecModel.validate_consistency` meaningful.

    Examples are not populated yet. The accessors exist
    (:meth:`~simulation_harness.openapi.parser.OpenAPIOperation.get_request_example`
    and its response counterpart) but wiring them needs a token-budget policy.
    """
    evidence: dict[str, OperationEvidence] = {}
    for op in spec.operations:
        description: str | None = (
            op.description if isinstance(op.description, str) else None
        )
        if description is not None:
            description = description.strip() or None
        summary = op.summary.strip() if isinstance(op.summary, str) else ""
        if description is not None and description == summary:
            description = None
        if description is None:
            continue
        evidence[op.operation_id] = OperationEvidence(description=description)
    return evidence


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
    evidence = extract_operation_evidence(spec)
    components = spec_dict.get("components", {}).get("schemas", {})
    # RPC/tool-style specs declare no components.schemas; fall back to the
    # schemas carried inline in operation request/response bodies.
    schema_source = components or inline_schema_evidence(spec)

    # Stage 1a — extract data model
    cb("extracting_model")
    dm = await guard_timeout(
        extract_data_model(schema_source, slug, extract_llm, retries=retries),
        stage="analyze:extract",
        timeout=timeout,
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
            records = await guard_timeout(
                classify_batch(batch, entity_names, classify_llm, retries=retries),
                stage="analyze:classify",
                timeout=timeout,
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
    ir = build_spec_model(slug, stubs, dm, semantics, evidence=evidence)
    consistency = ir.validate_consistency()
    if consistency:
        raise GenerationStageError("analyze", consistency)
    return ir
