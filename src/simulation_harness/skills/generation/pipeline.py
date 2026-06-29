"""Deterministic orchestrator for multi-step skill generation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import SecretStr

from simulation_harness.config.models import GenerationConfig
from simulation_harness.openapi.parser import OpenAPISpec
from simulation_harness.skills.generation.llm import StructuredCallError, build_chat
from simulation_harness.skills.generation.repair import GenerationStageError
from simulation_harness.skills.generation.stages.analyze import analyze
from simulation_harness.skills.generation.stages.assemble import (
    assemble_skill,
    render_preamble,
    validate_bundle,
)
from simulation_harness.skills.generation.stages.operations import (
    generate_section,
    plan_chunks,
)
from simulation_harness.skills.generation.stages.schema import generate_schema
from simulation_harness.skills.generation.stages.scenarios import generate_scenarios
from simulation_harness.skills.generation.stages.seed import generate_seed


@dataclass
class SkillBundle:
    skill_md: str
    schema: dict
    db: dict
    scenarios: list[dict] = field(default_factory=list)


def _noop(_: str) -> None:
    return None


async def run_pipeline(
    spec_dict: dict,
    slug: str,
    *,
    api_key: SecretStr | None,
    base_url: str | None,
    gen_config: GenerationConfig,
    model: str,
    progress_cb: Callable[[str], None] | None = None,
) -> SkillBundle:
    cb = progress_cb or _noop
    timeout = gen_config.stage_timeout_seconds

    def chat(params, json_mode):
        return build_chat(
            api_key=api_key,
            model=model,
            temperature=params.temperature,
            max_tokens=params.max_tokens,
            base_url=base_url,
            json_mode=json_mode,
        )

    # Stage 1 — analyze (extract → classify fan-out → merge; per-call timeouts inside)
    ir = await analyze(
        spec_dict,
        slug,
        extract_llm=chat(gen_config.extract, True),
        classify_llm=chat(gen_config.classify, True),
        retries=gen_config.repair_retries,
        batch_cap=gen_config.classify_batch_size,
        concurrency=gen_config.concurrency,
        timeout=timeout,
        progress_cb=cb,
    )

    spec = OpenAPISpec(spec_dict)
    chunks = plan_chunks(ir, threshold=gen_config.chunk_threshold)
    total = len(chunks)
    sem = asyncio.Semaphore(gen_config.concurrency)
    done = 0
    lock = asyncio.Lock()

    async def one_section(chunk):
        nonlocal done
        async with sem:
            section = await asyncio.wait_for(
                generate_section(
                    spec,
                    ir,
                    chunk,
                    chat(gen_config.operation, False),
                    retries=gen_config.repair_retries,
                ),
                timeout=timeout,
            )
        async with lock:
            done += 1
            cb(f"generating_ops {done}/{total}")
        return section

    async def schema_task():
        cb("designing_schema")
        return await asyncio.wait_for(
            generate_schema(
                ir,
                chat(gen_config.schema_seed, True),
                retries=gen_config.repair_retries,
            ),
            timeout=timeout,
        )

    async def scenarios_task():
        if not gen_config.scenarios_enabled:
            return []
        cb("imagining_scenarios")
        try:
            return await asyncio.wait_for(
                generate_scenarios(
                    ir,
                    chat(gen_config.scenarios, True),
                    count=gen_config.scenarios_count,
                    retries=gen_config.repair_retries,
                ),
                timeout=timeout,
            )
        except (GenerationStageError, StructuredCallError, asyncio.TimeoutError) as e:
            cb(f"scenarios_skipped {type(e).__name__}")
            return []

    # Stage: schema ∥ scenarios ∥ operation sections
    schema, scenarios, *sections = await asyncio.gather(
        schema_task(), scenarios_task(), *[one_section(c) for c in chunks]
    )

    # Stage: seed (depends on schema + scenarios)
    scenario_dicts = [s.model_dump() for s in scenarios]
    cb("seeding_database")
    db = await asyncio.wait_for(
        generate_seed(
            ir,
            schema,
            scenario_dicts,
            chat(gen_config.schema_seed, True),
            retries=gen_config.repair_retries,
        ),
        timeout=timeout,
    )

    # Stage: assemble + final validation
    cb("assembling")
    preamble = render_preamble(ir, scenario_dicts)
    skill_md = assemble_skill(ir, preamble, list(sections))
    errors = validate_bundle(ir, skill_md, schema, db)
    if errors:
        raise GenerationStageError("assemble", errors)
    return SkillBundle(
        skill_md=skill_md, schema=schema, db=db, scenarios=scenario_dicts
    )
