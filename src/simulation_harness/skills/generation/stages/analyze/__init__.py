"""Stage 1 orchestrator: spec → IR via extract → classify (fan-out) → merge."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.ir import Entity, OperationEvidence, SpecModel
from simulation_harness.skills.generation.llm import is_fatal_llm_error
from simulation_harness.skills.generation.repair import (
    GenerationStageError,
    guard_timeout,
)
from simulation_harness.skills.generation.stages.analyze.classify import (
    classify_batch,
    plan_classify_batches,
)
from simulation_harness.skills.generation.stages.analyze.enrich import (
    enrich_entities,
    structural_entities,
)
from simulation_harness.skills.generation.stages.analyze.extract import (
    extract_data_model,
)
from simulation_harness.skills.generation.stages.analyze.identity import derive_identity
from simulation_harness.skills.generation.stages.analyze.merge import (
    build_spec_model,
    compose_data_model,
    validate_coverage,
)
from simulation_harness.skills.generation.stages.analyze.sources import (
    collect_sources,
    inline_schema_evidence,
)
from simulation_harness.utils.logging import get_logger

logger = get_logger(__name__)

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
    enrich_llm=None,
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
    sources = collect_sources(spec, spec_dict)

    # Stage 1a-1 — derive the contract in code. This is the part that must not
    # vary between two generations of the same spec.
    cb("deriving_identity")
    identity = derive_identity(
        sources.identity, synthetic=sources.synthetic, deferred=sources.deferred
    )

    # Stage 1a-2 — enrich the derived entities with field detail. Degrades to
    # the structural floor: duller fields, identical contract.
    enriched: list[Entity] = []
    if identity.entities and enrich_llm is not None:
        cb("enriching_model")
        try:
            enriched = await guard_timeout(
                enrich_entities(identity, sources.enrich, enrich_llm, retries=retries),
                stage="analyze:enrich",
                timeout=timeout,
            )
        except Exception as e:
            # Broad on purpose: enrich only adds field prose to an already-
            # derived, contract-complete entity set, so no failure mode here
            # — GenerationStageError/StructuredCallError/StageTimeoutError from
            # a bad LLM payload, or a transport-level error such as a
            # connection reset — is worth discarding that contract for. A
            # code-level bug inside enrich_entities is caught by that module's
            # own unit tests, not by this handler.
            #
            # The exception is a settings fault: a rejected key, a model the
            # team cannot reach, or a name the gateway does not know. Nothing
            # downstream can succeed either, so softening it here only defers
            # the identical failure to the next call with its cause already
            # scrolled out of view (issue #13). Let those through.
            if is_fatal_llm_error(e):
                raise
            logger.warning(
                "enrich stage skipped (%s: %s) — entities keep their derived "
                "contract but lose descriptions, enums and relationships",
                type(e).__name__,
                e,
            )
            cb(f"enrich_skipped {type(e).__name__}")
            enriched = structural_entities(identity)
    elif identity.entities:
        enriched = structural_entities(identity)

    # Stage 1a-3 — LLM fallback. Scoped to the undecidable schemas when the
    # deterministic rule found anything; given the whole map when it found
    # nothing, so a spec with no usable response schemas still generates.
    fallback = None
    if identity.entities:
        # Scoped: only what the rule could not decide. An empty leftovers map
        # means the rule decided everything, so there is nothing to ask about.
        leftovers = {name: sources.identity[name] for name in identity.undecidable}
        call_fallback = bool(leftovers)
    else:
        # Nothing was decidable in code. Hand over everything we have and call
        # unconditionally — even with an empty map. That is exactly what the
        # extract stage receives today for a spec whose operations carry prose
        # but no schemas, and skipping the call would turn those specs from
        # "generates" into "hard fails".
        leftovers = dict(sources.enrich)
        call_fallback = True
    if call_fallback:
        cb("extracting_model")
        fallback = await guard_timeout(
            extract_data_model(
                leftovers,
                slug,
                extract_llm,
                retries=retries,
                derived=identity if identity.entities else None,
                array_shaped=sources.deferred,
            ),
            stage="analyze:extract",
            timeout=timeout,
        )

    api_name = spec_dict.get("info", {}).get("title") or slug
    dm, provenance = compose_data_model(api_name, identity, enriched, fallback)
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
    ir.identity_provenance = provenance
    consistency = ir.validate_consistency()
    if consistency:
        raise GenerationStageError("analyze", consistency)
    return ir
