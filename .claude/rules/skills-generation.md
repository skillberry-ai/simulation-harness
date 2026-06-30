---
paths:
  - "src/simulation_harness/skills/**/*.py"
---

# Skill-generation rules

- The generation pipeline lives in `skills/generation/stages/` and is composed in `skills/generator.py`. Keep stage order: analyze → operations → scenarios → schema → seed → assemble.
- Any spec-derived identifier used as a skill or tool name must pass `sanitize_skill_name` (`skills/generation/naming.py`) — it strips `/`, `.`, and other unsafe chars (path-traversal mitigation, see `THREAT_MODEL.md` T4).
- Prompt/skill text comes from Jinja2 templates under `skills/assets/`; register new templates in `pyproject.toml` `package-data`.
- Generation is skipped when `<skills_folder>/<name>/SKILL.md` already exists unless `regenerate: true`.
- See the `add-generation-stage` skill for the full pattern.
