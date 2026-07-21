# Simulation Skill Generation

This document describes how the harness turns an OpenAPI specification into a
**simulation skill** — the bundle of files (`SKILL.md`, `schema.json`,
`db.json`, …) that an LLM-driven agent later loads to impersonate the described
API. It covers the assumptions made on the input, the generation pipeline, each
stage in turn, and the output files.

It is deliberately high-level: it names the modules and functions involved and
points to code, but does not reproduce implementation detail. Use it as a map.

> Scope note: this document covers **skill generation only** — the offline
> transformation of a spec into files on disk. It does *not* cover how the
> running agent consumes those files at request time (see `CLAUDE.md` →
> "Request flow").

## 1. Assumptions on the input

The only input to generation is an OpenAPI specification. It reaches the
generator through any of three entry points, all converging on the same reuse
gate (`SkillRegistry.ensure_skill`, §2):

- `POST /api/v1/simulation` — combined create (generate **and** start).
- `POST /api/v1/simulation/setup` — generate artifacts only, then rest at the
  `generated` status (see [docs/api.md](api.md)).
- `uv run python -m simulation_harness.setup_cli <spec>` — offline, server-less
  generation for build time; exits non-zero on a bad spec.

For the two HTTP paths the spec is a JSON object in the request body; the CLI
loads it from a `.json`/`.yaml` file. Before any generation runs, the spec is
validated (`api/v1/simulations.py`, `setup_cli.py`):

- **Must be a valid OpenAPI 3.x document.** It is checked with
  `validate_openapi_dict()` (`openapi/parser.py:325`), which delegates to
  `openapi_spec_validator`. Failures return **HTTP 422**.
- **Must parse into at least one operation.** It is loaded into
  `OpenAPISpec` (`openapi/parser.py:155`), whose `_parse_operations()` walks
  `paths` × methods. Each operation's `operationId` is sanitized
  (`sanitize_operation_id`, `openapi/parser.py:25`) into a collision-free,
  ≤64-char identifier that doubles as the MCP tool name. The *same* sanitized
  ids flow into generation, so the documentation and the exposed tools agree.
- **A data model must be derivable.** Generation needs entity shapes. These
  come from `components.schemas` when present. For RPC/tool-style specs that
  declare none, the harness synthesizes evidence from each operation's
  request/response bodies (`inline_schema_evidence`,
  `stages/analyze/__init__.py:41`). If neither yields any entity, generation
  fails (`GenerationStageError("extract", …)`).
- **A name is derived, not required.** The simulation/skill name comes from the
  request `name` if given, otherwise from `info.title`, sanitized via
  `sanitize_skill_name` (`api/v1/simulations.py:143-150`). This name is the
  skill directory and the `SKILL.md` frontmatter `name`.

Generation also assumes an LLM is reachable: `LLM_API_KEY` (and optional
`LLM_API_BASE`) must be configured, and the model is taken from runtime config.

## 2. Pipeline overview

Generation is gated, then delegated, then orchestrated. Three entry points
converge on the reuse gate:

```
POST /api/v1/simulation        ─┐  (SimulationHost.declare_simulation — generate + start)
POST /api/v1/simulation/setup  ─┤  (SimulationHost.setup_simulation   — generate only)
python -m simulation_harness.setup_cli ─┘  (offline — no host, no running instance)
  └─ SkillRegistry.ensure_skill           core/skill_registry.py     ← reuse vs generate gate
       └─ SkillGenerator.generate_skill    skills/generator.py        ← atomic file writer
            └─ run_pipeline                skills/generation/pipeline.py  ← stage orchestrator
```

The two HTTP paths route through `SimulationCreator._pipeline`
(`core/simulation_creator.py`), which calls `ensure_skill`; the CLI calls
`ensure_skill` directly. Only the combined path continues past generation into
instance startup.

**Reuse gate.** `SkillRegistry.ensure_skill` (`core/skill_registry.py:31`)
reuses an existing skill only if all four core files (`SKILL.md`,
`schema.json`, `db.json`, `api.json`) are present *and* `regenerate` is false.
Otherwise it regenerates. (`regenerate` originates from the `regenerate_skill`
flag on the create/setup requests, or the CLI's `--regenerate`.)

**Orchestrator.** `run_pipeline` (`skills/generation/pipeline.py:42`) is a
deterministic async orchestrator: it sequences the LLM stages, fans work out
concurrently where stages are independent, applies a per-call timeout, and
returns a `SkillBundle` (the in-memory artifacts). `SkillGenerator` is
responsible only for writing that bundle to disk atomically.

The stages, and their data dependencies:

```
        ┌──────────────────────────────────────────────┐
spec ─▶  │ Stage 1  ANALYZE                              │
        │   extract data model → classify ops → merge   │ → IR (SpecModel)
        └──────────────────────────────────────────────┘
                              │ IR
        ┌───────────┬─────────┼──────────┬──────────────┐
        ▼           ▼         ▼          ▼
 Stage 2/3     Stage 4   Stage 5    Stage 6
 OPERATIONS    SCHEMA    SCENARIOS  BEHAVIOR
 (per-chunk    (JSON     (optional, (optional,
  sections)    Schema)   best-eff.) best-eff.)
        │           │         │          │
        │           └────┬────┘          │   schema + scenarios
        │                ▼               │
        │        Stage 7 SEED (db.json)  │
        │                │               │
        └────────┬───────┴───────────────┘
                 ▼   (operations + behavior feed the preamble)
         Stage 8 ASSEMBLE + VALIDATE → SkillBundle
```

Stages 3 (operation sections), 4 (schema), 5 (scenarios), and 6 (behavior) run
concurrently via a single `asyncio.gather` (`pipeline.py:159`). Stage 7 (seed)
waits on schema + scenarios; Stage 8 assembles everything — the preamble
(including the behavior section), the operation sections, and the seed/schema —
and validates before the bundle is returned.

**Cross-cutting machinery:**

- **LLM client** — `build_chat` (`skills/generation/llm.py`) constructs a
  `langchain_openai.ChatOpenAI` per call, with per-stage temperature/max-tokens
  and optional JSON mode.
- **Repair loop** — `with_repair` (`skills/generation/repair.py:20`) wraps each
  artifact in a produce→validate→re-prompt-with-feedback loop, up to
  `repair_retries + 1` attempts. Validation failures become feedback for the
  next attempt; exhausting retries raises `GenerationStageError`.
- **Tuning** — `GenerationConfig` (`config/models.py:87`) holds all knobs:
  per-stage `StageParams`, `concurrency` (5), `chunk_threshold` (40),
  `classify_batch_size` (40), `repair_retries` (2),
  `stage_timeout_seconds` (120), the scenario toggles
  (`scenarios_enabled`, `scenarios_count`), and the behavior toggle
  (`behavior_enabled`). These surface in `harness.yaml`.

## 3. The stages

### Stage 1 — Analyze (spec → IR)

`analyze()` (`skills/generation/stages/analyze/__init__.py:70`) builds the
intermediate representation (`SpecModel`, see §4) in three sub-steps:

1. **Extract data model** — `extract_data_model`
   (`stages/analyze/extract.py`). Feeds the component (or synthesized) schemas
   to the LLM (prompt `assets/generation/extract.md`, JSON mode) to produce
   entities: name, collection, primary key, fields, relationships. Aborts if no
   entities are found.
2. **Classify operations** — operations are bin-packed into batches by tag
   (`plan_classify_batches`) and classified in a bounded concurrent fan-out
   (`classify_batch`, `stages/analyze/classify.py`; prompt
   `assets/generation/classify.md`). Each operation gets a `kind`
   (create/read/update/delete/list/search/action) and behavioral `patterns`.
3. **Merge + validate** — `build_spec_model` (`stages/analyze/merge.py`)
   combines extraction and classification into the IR. Coverage
   (`validate_coverage`) and cross-reference consistency
   (`SpecModel.validate_consistency`) are checked; inconsistencies raise
   `GenerationStageError`.

### Stages 2 & 3 — Operation sections

`plan_chunks` (`stages/operations.py:27`) groups operations by tag and splits
groups larger than `chunk_threshold` into chunks. Each chunk is then rendered
to Markdown by `generate_section` (`stages/operations.py:59`; prompt
`assets/generation/operation.md`, text mode) — one `### METHOD /path` section
per operation, documenting the simulated behavior, response shape, and error
when-clauses. Each section also carries a **Derived fields** note listing which
response fields are computed rather than copied from the request or store; the
*how* (ranges, formulas, ordering) is deferred to the global behavior section
(Stage 6), keeping numeric decisions in one authoritative place. Chunks generate
concurrently, bounded by a semaphore (`concurrency`).

### Stage 4 — Schema

`generate_schema` (`stages/schema.py:37`; prompt `assets/generation/schema.md`,
JSON mode) designs a JSON Schema (Draft 2020-12) covering every collection in
the IR. The result is validated as a well-formed schema inside the repair loop.

### Stage 5 — Scenarios (optional)

`generate_scenarios` (`stages/scenarios.py:42`; prompt
`assets/generation/scenarios.md`, JSON mode) produces `scenarios_count`
representative user stories (`title`, `intent`, `operations`). This stage is
**best-effort**: it is skipped entirely if `scenarios_enabled` is false, and any
error or timeout is swallowed (`pipeline.py:128`) so it cannot fail the build —
generation simply proceeds with no scenarios.

### Stage 6 — Behavior (optional)

`generate_behavior` (`stages/behavior.py:50`; prompt
`assets/generation/behavior.md`, text mode) runs once over the whole IR and
produces a single Markdown block — the authoritative source for *how* the
simulator computes and keeps values consistent, especially numeric ones. It has
three fixed subsections: **Numeric Ranges and Ordering** (domain value ranges
and ordering constraints), **Derivation Rules** (cross-field/cross-operation
formulas — e.g. a payment amount equals the sum of per-item charges plus fees),
and **On-Demand Generation Rules** (deterministic generation of unseeded numeric
records so repeat calls stay stable). This section is injected into the preamble
under *Realism Guidelines* (Stage 8) and is what the per-operation *Derived
fields* notes defer to.

Like scenarios, this stage is **best-effort**: it is skipped when
`behavior_enabled` is false, and any error or timeout is swallowed
(`pipeline.py:140`, emitting `behavior_skipped …`) so it cannot fail the build —
the preamble then falls back to its static realism invariants. Its
`with_repair` validation requires all three subsection headings to be present.

### Stage 7 — Seed database

`generate_seed` (`stages/seed.py:39`; prompt `assets/generation/seed.md`, JSON
mode) generates the initial `db.json` contents. It depends on the schema and
the scenarios so the seed data is both schema-valid and rich enough to satisfy
the example scenarios. The generated data is validated against the Stage-4
schema (`validate_schema_and_db`) inside the repair loop.

### Stage 8 — Assemble + validate

- `render_preamble` (`stages/assemble.py:25`) renders the Jinja2 template
  `assets/generation/skill_preamble.jinja2` with the API name, collection list,
  scenarios, and the Stage-6 behavior section — producing the frontmatter plus
  the fixed guidance sections (core principles, state management, schema
  reference, error handling, realism, example scenarios). The behavior section,
  when present, is injected under *Realism Guidelines*; when absent (stage
  disabled or skipped) only the static realism invariants remain.
- `assemble_skill` (`stages/assemble.py:34`) concatenates the preamble and the
  per-operation sections, and forces the frontmatter `name` to the slug.
- `validate_bundle` (`stages/assemble.py:39`) is the final gate: it confirms
  every IR operation has a section in `SKILL.md`, the frontmatter name matches
  the slug, and the schema/db pair validates. Any error raises
  `GenerationStageError("assemble", …)` and aborts the whole generation.

## 4. The intermediate representation (IR)

All stages after Analyze share one in-memory model, `SpecModel`
(`skills/generation/ir.py`). It is the contract between stages and the single
source of truth for "what operations and entities exist". Key parts:

- **`Entity`** — `name`, `collection`, `primary_key`, `fields`,
  `relationships`, plus `fingerprint_fields` / `temporal_fields` hints.
- **`Operation`** — sanitized `operation_id`, `method`, `path`, `tag`,
  `summary`, owning `entity`, `kind`, and `patterns`.
- **`StoreMetadata`** — the `collections` list and `pk_map` (collection →
  primary key).

`SpecModel.validate_consistency()` enforces that operations reference known
entities and that every entity/pk-map collection is declared — this is what
keeps `SKILL.md`, `schema.json`, and `db.json` mutually coherent.

## 5. Output files

`SkillGenerator.generate_skill` (`skills/generator.py:51`) writes the bundle
**atomically**: it writes into a temp dir
(`<skills_folder>/.<name>.tmp-<uuid>/`), then `rename`s it onto
`<skills_folder>/<name>/`. On any failure the temp dir is removed, so a
half-written skill is never observable. The skills folder defaults to
`./skills-store` (per `harness.yaml`).

The resulting `<skills_folder>/<name>/` directory contains:

| File | Source | Contents |
|---|---|---|
| `SKILL.md` | `assemble_skill` (Stage 8) | Agent Skills document: YAML frontmatter (`name`, `description`) + guidance preamble (including the Stage-6 behavior section under *Realism Guidelines*) + one Markdown section per operation, each with a *Derived fields* note. This is what the agent reads on demand via progressive disclosure. |
| `schema.json` | `generate_schema` (Stage 4) | JSON Schema (Draft 2020-12) describing every collection — the authoritative shape of the state store. |
| `db.json` | `generate_seed` (Stage 7) | Initial seed entities, schema-valid, loaded into the state store on first use. |
| `scenarios.json` | `generate_scenarios` (Stage 5) | Representative user stories (`title`, `intent`, `operations`). **Only written when scenarios were generated** — omitted otherwise. |
| `api.json` | input spec (`generator.py:103`) | Verbatim copy of the input OpenAPI spec, kept for reference, reuse checks, and so `POST /api/v1/simulation/start` can reconstruct the spec at run time without a fresh submission. |

The reuse gate (§2) treats a skill as complete only when `SKILL.md`,
`schema.json`, `db.json`, and `api.json` all exist; `scenarios.json` is
optional and does not affect reuse.

## 6. Failure behavior (summary)

- Invalid/unparseable spec → **HTTP 422** before generation starts.
- A required stage (extract, classify, schema, seed, operations, assemble)
  exhausting its repair retries or timing out → `GenerationStageError`, which
  fails the creation; `SkillGenerator` wraps it in a `RuntimeError` and removes
  the temp dir.
- Scenarios and behavior are the non-fatal stages: failures are logged via the
  progress callback (`scenarios_skipped …` / `behavior_skipped …`) and
  generation continues (behavior falls back to the static realism invariants).

## Code reference index

| Concern | Location |
|---|---|
| Route + input validation | `api/v1/simulations.py:119` |
| Reuse vs generate gate | `core/skill_registry.py:31` |
| Atomic file writer | `skills/generator.py:51` |
| Pipeline orchestrator | `skills/generation/pipeline.py:42` |
| Stage 1 analyze | `skills/generation/stages/analyze/__init__.py:70` |
| Stage 2/3 operations | `skills/generation/stages/operations.py` |
| Stage 4 schema | `skills/generation/stages/schema.py:37` |
| Stage 5 scenarios | `skills/generation/stages/scenarios.py:42` |
| Stage 6 behavior | `skills/generation/stages/behavior.py:50` |
| Stage 7 seed | `skills/generation/stages/seed.py:39` |
| Stage 8 assemble | `skills/generation/stages/assemble.py` |
| IR model | `skills/generation/ir.py` |
| LLM client | `skills/generation/llm.py` |
| Repair loop | `skills/generation/repair.py:20` |
| Tuning config | `config/models.py:87` |
| Prompt templates | `skills/assets/generation/*.md`, `*.jinja2` |
