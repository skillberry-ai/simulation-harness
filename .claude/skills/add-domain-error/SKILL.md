---
name: add-domain-error
description: Use when introducing a new domain error/exception that must surface as a specific HTTP status or MCP error code in simulation-harness.
---

# Add a domain error

Reference: `src/simulation_harness/utils/errors.py` (definitions) and `src/simulation_harness/main.py` (mapping).

## Steps

1. **Define the exception** in `src/simulation_harness/utils/errors.py`, subclassing the existing base domain error.
2. **Map it to HTTP** in `src/simulation_harness/main.py`'s exception handlers. Existing mappings:
   - `SimulationAlreadyExistsError`, `PortInUseError` → 409
   - `SimulationNotFoundError` → 404
   - `OpenAPIValidationError` → 422
   - `SessionExpiredError` → 410
   - `ConcurrentQueueFullError` → 503
3. **Preserve MCP reason codes**: `tools/call` errors return a human-readable text block first, then a JSON block `{"reason": "<code>", ...}` last. Stable codes: `session_expired` (+ `limit`, `observed`), `concurrent_queue_full`, `tool_execution_failed`. Add a new stable code rather than overloading an existing one.
4. **Test** the mapping in `tests/unit/test_main_error_handlers.py`.

## Gotchas

- Keep mapping in `main.py` — never catch domain errors in route handlers.
