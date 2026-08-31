---
name: add-generation-stage
description: Use when adding or modifying a stage in the skill-generation pipeline that turns an OpenAPI spec into an Agent Skill.
---

# Add a skill-generation stage

Reference: stages in `src/simulation_harness/skills/generation/stages/` (e.g. `operations.py`, `scenarios.py`, `schema.py`, `seed.py`, `assemble.py`), wired together in `src/simulation_harness/skills/generator.py`.

## Steps

1. **Create the stage** under `skills/generation/stages/`, mirroring an existing stage's structure (input model → transform → output model).
2. **Wire it into the pipeline** in `skills/generator.py` in the correct order (analyze → operations → scenarios → schema → seed → assemble).
3. **Templates**: if the stage emits prompt/skill text, add a Jinja2 template under `skills/assets/generation/` and register it in `pyproject.toml` `package-data`.
4. **Names**: any spec-derived identifier used as a skill/tool name must pass `sanitize_skill_name` (`skills/generation/naming.py`).
5. **Shape vs. intent**: if your stage input gets serialized wholesale into a prompt, keep it shape-only (fields like `operation_id`/`method`/`path`/`kind`) — operation-level prose belongs in `SpecModel.evidence` and must be read explicitly by stages that need it, not carried on the shape projection.
6. **Test** the stage in isolation under `tests/unit/`.

## Gotchas

- New stage modules currently sit under the mypy `ignore_errors` backlog (`pyproject.toml`). Prefer adding full type annotations and leaving the new module off that list.
- Skill reuse: generation is skipped if `<skills_folder>/<name>/SKILL.md` exists unless `regenerate: true`.
