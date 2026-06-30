---
paths:
  - "src/simulation_harness/api/**/*.py"
---

# API layer rules

- Handlers are thin: validate input, call into `core`/`SimulationHost`, return a model. No business logic in routes.
- Raise domain errors from `utils/errors.py`; never translate to HTTP status here — mapping lives in `main.py`.
- Request/response shapes are Pydantic models in `models/`.
- After changing any endpoint or model, run `make openapi` to refresh `openapi.json`.
- See the `add-api-endpoint` skill for the full pattern.
