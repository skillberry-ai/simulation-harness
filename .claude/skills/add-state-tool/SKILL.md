---
name: add-state-tool
description: Use when adding a new state_* tool that the LLM agent can call to read or mutate session-scoped simulation state.
---

# Add a state tool

Reference: `src/simulation_harness/state/tools.py`, registered via `state/registry.py`, backed by `state/store.py`.

## Steps

1. **Implement the tool** in `src/simulation_harness/state/tools.py`, following the signature/shape of existing `state_*` tools.
2. **Register it** in `src/simulation_harness/state/registry.py` so the agent can discover it.
3. **Persist through the store** (`state/store.py`) — operate on the `schema.json`/`db.json`-backed store; do not hold ad-hoc state.
4. **Document the contract**: the runtime system prompt (`agent/templates/simulator_system.jinja2`) carries the state mechanism + JSON contract. Per-operation detail belongs in the generated skill, not the system prompt.
5. **Test** under `tests/unit/` against the store.

## Gotchas

- `state/` must not import from `api/`, `core/`, or `mcp_integration/` (import-linter contract).
- State is session-scoped and ephemeral — reset clears it.
