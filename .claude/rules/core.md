---
paths:
  - "src/simulation_harness/core/**/*.py"
---

# Core / lifecycle rules

- `SimulationHost` is a singleton enforcing **one active simulation per process**. Mutate its state only inside `_lifecycle_lock`; new lifecycle operations follow the same pattern.
- A single agent thread accumulates context across all `tools/call` invocations for a simulation's lifetime.
- Sessions expire by `max_messages`, idle timeout, or explicit reset. Only **successful** tool calls increment the counter; failed calls preserve thread state.
- Concurrency serializes through `_queue_lock`; when `_current_queue_depth >= max_queue_depth`, raise `ConcurrentQueueFullError` (→ 503 / MCP `concurrent_queue_full`).
