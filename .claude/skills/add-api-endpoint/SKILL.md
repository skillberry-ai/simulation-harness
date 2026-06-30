---
name: add-api-endpoint
description: Use when adding a new REST endpoint to the simulation-harness FastAPI service. Covers request/response models, routing, and error mapping.
---

# Add a REST endpoint

Reference implementation: `src/simulation_harness/api/v1/simulations.py`.

## Steps

1. **Define request/response models** as Pydantic models in `src/simulation_harness/models/` (keep `models/` import-free of higher layers — see the import-linter contract in `pyproject.toml`).
2. **Add the route** in the relevant `api/v1/*.py` router. Inject dependencies the same way existing handlers do; keep handlers thin.
3. **Raise domain errors** from `src/simulation_harness/utils/errors.py` — do **not** translate to HTTP inside the handler.
4. **Map the error** centrally in `src/simulation_harness/main.py` (see the exception handlers). Reuse an existing status mapping where possible.
5. **Refresh the OpenAPI spec**: `make openapi` (regenerates `openapi.json`).
6. **Test**: add unit tests under `tests/unit/` and an integration test under `tests/integration/` mirroring existing ones.

## Gotchas

- Error mapping stays centralized in `main.py` — route handlers never catch domain errors (see CLAUDE.md conventions).
- If the endpoint touches simulation lifecycle, go through `SimulationHost` inside its `_lifecycle_lock`.
