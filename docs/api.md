# Simulation Harness API

This document is the integrator's reference for driving the harness end-to-end:
create a simulation from an OpenAPI spec, connect an MCP client to the simulated
tools, and tear it down. Everything below is authoritative against the running
service — for a live, schema-typed view, browse `/docs` (Swagger UI), `/redoc`,
or `/openapi.json` on the running harness.

## Contents

- [Overview](#overview)
- [Base URL and authentication](#base-url-and-authentication)
- [End-to-end walkthrough](#end-to-end-walkthrough)
- [REST endpoints](#rest-endpoints)
  - [`POST /api/v1/simulation`](#post-apiv1simulation) — create (setup + start)
  - [`POST /api/v1/simulation/setup`](#post-apiv1simulationsetup) — generate artifacts only
  - [`POST /api/v1/simulation/start`](#post-apiv1simulationstart) — run from baked artifacts
  - [`GET /api/v1/simulation`](#get-apiv1simulation) — status
  - [`DELETE /api/v1/simulation`](#delete-apiv1simulation) — tear down
  - [`POST /api/v1/simulation/reset`](#post-apiv1simulationreset) — reset session
  - [`GET /api/v1/simulation/tools`](#get-apiv1simulationtools) — list MCP tools
  - [`GET /api/v1/simulation/state`](#get-apiv1simulationstate) — state snapshot
  - [`GET /api/v1/simulation/database`](#get-apiv1simulationdatabase) — read seed `db.json`
  - [`GET /api/v1/simulation/schema`](#get-apiv1simulationschema) — read `schema.json`
  - [`PUT /api/v1/simulation/database`](#put-apiv1simulationdatabase) — replace `db.json` + reset
  - [`GET /health`, `/healthz`, `/readyz`](#health-and-probe-endpoints)
- [MCP transport](#mcp-transport)
  - [SSE](#sse-transport-default)
  - [Streamable HTTP](#streamable-http-transport)
  - [Sidecar port](#sidecar-port)
- [Errors](#errors)
- [Session lifecycle](#session-lifecycle)

## Overview

The harness has two surfaces:

1. **REST control plane** at `/api/v1/...` — create, inspect, reset, and delete
   the active simulation; list tool schemas; inspect state.
2. **MCP transport** at `/mcp/...` — the simulated tools themselves, exposed as
   a standard MCP server over SSE or Streamable HTTP. One MCP tool per OpenAPI
   operation in the spec you submitted.

**Only one simulation is active per harness process at a time.** Creating a new
one while another is active returns `409`. Either `DELETE` first or pass
`regenerate_skill: true` to refresh the existing simulation's skill in place.

`POST /api/v1/simulation` couples two steps — **setup** (generate the skill
artifacts from the spec, the slow LLM-driven half) and **start** (open a running
session from those artifacts, the fast deterministic half). They are also
exposed separately: [`POST /api/v1/simulation/setup`](#post-apiv1simulationsetup)
generates artifacts and stops at `generated`, and
[`POST /api/v1/simulation/start`](#post-apiv1simulationstart) opens a session
from artifacts already on disk (no spec required). This split maps onto a
build-then-run lifecycle — generate once at build time, start on every boot. The
build-time equivalent of setup is the offline CLI
`uv run python -m simulation_harness.setup_cli <spec>`. The generation pipeline
itself is documented in [docs/simulation-generation.md](simulation-generation.md).

## Base URL and authentication

- Default base URL: `http://localhost:8086` (set in `config/harness.yaml`; the
  README's port `8000` example is out of date).
- The harness itself has no authentication — it's intended to run on a trusted
  network or behind an ingress that adds auth.
- The `LLM_API_KEY` (and optional `LLM_API_BASE`) used by the simulation agent
  come from `.env` or environment variables, **not** from the YAML.

Examples below assume `BASE=http://localhost:8086`.

## End-to-end walkthrough

A complete run against a tiny Petstore spec.

### 1. Create the simulation

```bash
curl -sS -X POST "$BASE/api/v1/simulation" \
  -H 'content-type: application/json' \
  -d '{
    "openapi_spec": {
      "openapi": "3.0.3",
      "info": {"title": "Petstore", "version": "1.0.0"},
      "paths": {
        "/pets": {
          "get": {
            "operationId": "listPets",
            "summary": "List pets",
            "responses": {
              "200": {
                "description": "A list of pets",
                "content": {
                  "application/json": {
                    "schema": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id":   {"type": "integer"},
                          "name": {"type": "string"},
                          "tag":  {"type": "string"}
                        },
                        "required": ["id", "name"]
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }'
```

Response (`202 Accepted`):

```json
{
  "name": "petstore",
  "status": "pending",
  "session_state": null,
  "mcp_url": null,
  "created_at": "2026-06-14T12:34:56.000000+00:00",
  "progress": {
    "phase": null,
    "started_at": "2026-06-14T12:34:56.000000+00:00",
    "updated_at": "2026-06-14T12:34:56.000000+00:00"
  },
  "error": null
}
```

Creation runs in the background. `session_state` and `mcp_url` are `null` until
the simulation is ready.

### 2. Poll until ready

```bash
curl -sS "$BASE/api/v1/simulation"
```

Poll this endpoint until `status` becomes `"ready"` (or `"failed"`). Typical
wait is a few seconds when a cached skill exists, or 10–60 seconds for
first-time skill generation. The default creation budget is 120 seconds
(`creation.max_duration_seconds` in `harness.yaml`).

Possible `status` values:

| Value | Meaning |
|---|---|
| `pending` | Accepted; background task has not started yet. |
| `generating_skill` | LLM is generating the skill from the spec. |
| `generated` | Artifacts generated and resting on disk; no running instance. Reached only via `POST /api/v1/simulation/setup`; `start` advances from here to `ready`. |
| `initializing` | Skill is ready; agent thread is being set up. |
| `ready` | Simulation is fully operational; MCP tools are available. |
| `failed` | Creation failed; see `error` for details. |

Response when ready:

```json
{
  "name": "petstore",
  "status": "ready",
  "session_state": {
    "tool_call_count": 0,
    "max_messages": 100,
    "idle_timeout_seconds": 3600,
    "last_activity": null,
    "queue_depth": 0,
    "max_queue_depth": 8,
    "seconds_since_last_call": null
  },
  "mcp_url": "http://localhost:8086/mcp/petstore",
  "created_at": "2026-06-14T12:34:56.000000+00:00",
  "progress": {
    "phase": null,
    "started_at": "2026-06-14T12:34:56.000000+00:00",
    "updated_at": "2026-06-14T12:35:03.000000+00:00"
  },
  "error": null
}
```

The `mcp_url` field is only populated when `status == "ready"`. Where you
actually connect depends on the configured `mcp.transport` — see
[MCP transport](#mcp-transport).

### 3. List the tools the simulation exposes

```bash
curl -sS "$BASE/api/v1/simulation/tools"
```

```json
[
  {
    "name": "listPets",
    "description": "List pets",
    "inputSchema": {
      "type": "object",
      "properties": {},
      "required": []
    }
  }
]
```

Tool names are taken verbatim from each operation's `operationId`.

### 4. Call a tool over MCP

Using SSE (default), with the `mcp` Python SDK:

```python
import asyncio
from mcp import ClientSession
from mcp.client.sse import sse_client

async def main():
    async with sse_client("http://localhost:8086/mcp/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([t.name for t in tools.tools])  # ['listPets']
            result = await session.call_tool("listPets", {})
            print(result.isError, result.content)

asyncio.run(main())
```

The agent synthesises a schema-valid response from the spec — for example a
JSON array of two or three pet objects in the `text` content block.

### 5. Reset the session counters

After a test run, reset counters without tearing the simulation down:

```bash
curl -sS -X POST "$BASE/api/v1/simulation/reset"
# {"message": "Session reset successfully"}
```

This zeroes `tool_call_count` and `queue_depth` and clears `last_activity`. The
underlying agent thread is reset as well, so subsequent calls start with a
fresh context.

### 6. Tear down

```bash
curl -sS -X DELETE "$BASE/api/v1/simulation" -o /dev/null -w "%{http_code}\n"
# 204
```

The MCP server is shut down and a new simulation can now be created.

## REST endpoints

All paths are under `/api/v1/`. Request and response bodies are `application/json`.

### `POST /api/v1/simulation`

Create the active simulation from an OpenAPI 3.x spec.

**Request body**

| Field | Type | Default | Description |
|---|---|---|---|
| `openapi_spec` | object | required | Parsed OpenAPI 3.x document. |
| `name` | string | spec `info.title` | Override for the simulation name. Lowercased and spaces are replaced with `-`. |
| `regenerate_skill` | boolean | `false` | Force LLM regeneration of the skill even if `<skills_folder>/<name>/SKILL.md` already exists. |
| `mcp_port` | integer (1–65535) | harness port | If set, the MCP server is started on this dedicated port instead of being mounted on the harness app. |

**Body limit:** 10 MB. Larger bodies return `413`.

**Responses**

- `202 Accepted` — `SimulationResponse` with `status: "pending"` (see [walkthrough §1](#1-create-the-simulation)). Creation continues in the background; poll `GET /api/v1/simulation` until `status` is `"ready"` or `"failed"`. The default creation budget is 120 seconds, configurable via `creation.max_duration_seconds` in `harness.yaml`.
- `409 Conflict` — a simulation is already active, or the requested `mcp_port` is in use.
- `413 Payload Too Large` — body exceeds 10 MB.
- `422 Unprocessable Entity` — OpenAPI validation or parsing failed.

**Example**

```bash
curl -sS -X POST "$BASE/api/v1/simulation" \
  -H 'content-type: application/json' \
  -d @petstore.openapi.json
```

### `POST /api/v1/simulation/setup`

Generate the skill artifacts (`SKILL.md`, `schema.json`, `db.json`, `api.json`)
from an OpenAPI spec **without** starting a session. This is the slow,
LLM-driven half of `POST /api/v1/simulation` on its own — use it to bake
artifacts ahead of time (e.g. at container-build time) so `start` can open a
session later with no LLM cost or cross-replica drift.

**Request body** — identical to
[`POST /api/v1/simulation`](#post-apiv1simulation) (`openapi_spec`, optional
`name`, `regenerate_skill`). `mcp_port` is not used (no session is started).

**Body limit:** 10 MB. Larger bodies return `413`.

**Responses**

- `202 Accepted` — `SimulationResponse` with `status: "pending"`. Generation
  runs in the background; poll `GET /api/v1/simulation` until `status` is
  `"generated"` (success) or `"failed"`. A `generated` record holds the single
  simulation slot but runs no agent, so `session_state` and `mcp_url` stay `null`.
- `409 Conflict` — a simulation record already exists (any status). `DELETE` it first.
- `413 Payload Too Large` — body exceeds 10 MB.
- `422 Unprocessable Entity` — OpenAPI validation or parsing failed.

```bash
curl -sS -X POST "$BASE/api/v1/simulation/setup" \
  -H 'content-type: application/json' \
  -d @petstore.openapi.json
# 202; poll GET /api/v1/simulation until status == "generated"
```

The offline, server-less equivalent is the setup CLI, which writes the same
artifacts and **exits non-zero** on a bad spec (so a build fails fast):

```bash
uv run python -m simulation_harness.setup_cli petstore.openapi.json \
  --name petstore [--regenerate] [--config config/harness.yaml]
# prints the artifact directory on success
```

### `POST /api/v1/simulation/start`

Open a running session from a skill's **already-generated** artifacts. This
never calls the LLM generator; the OpenAPI spec is reconstructed from the baked
`api.json`, so **no spec is sent** in the request.

**Request body**

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Name of the skill whose artifacts to start. Sanitized like the create `name`. |
| `mcp_port` | integer (1–65535) | harness port | If set, the MCP server is started on this dedicated port instead of being mounted on the harness app. |

**Responses**

- `202 Accepted` — `SimulationResponse` with `status: "pending"`. Poll
  `GET /api/v1/simulation` until `status` is `"ready"` or `"failed"`. If a
  `generated` record for `name` already exists, `start` consumes it (advancing
  the same record); otherwise it opens a fresh session from disk.
- `404 Not Found` — no complete artifacts exist for `name`
  (`SimulationArtifactsNotFoundError`; the response body lists the `missing` files).
- `409 Conflict` — a `ready` simulation already occupies the slot. `DELETE` it first.

```bash
curl -sS -X POST "$BASE/api/v1/simulation/start" \
  -H 'content-type: application/json' \
  -d '{"name": "petstore"}'
# 202; poll GET /api/v1/simulation until status == "ready"
```

**Auto-start on boot.** The harness can open a session automatically at startup
from `startup.autostart_simulation` in `harness.yaml` (or the
`HARNESS_AUTOSTART_SIMULATION` env var). With no name configured it discovers
baked skills: **0** complete skills → boot idle; **1** → start it; **more than
one** → start the most recently generated skill and log a warning. A configured
name whose artifacts are missing fails readiness (see
[`/readyz`](#health-and-probe-endpoints)).

### `GET /api/v1/simulation`

Return the active simulation's current record: status, creation progress, and
session counters. Use this to poll after a `POST` until `status` reaches
`"ready"` or `"failed"`. The response shape is identical to the `202` response
from `POST`, with `session_state` and `mcp_url` populated once `status == "ready"`.

```bash
curl -sS "$BASE/api/v1/simulation"
```

- `200 OK` — `SimulationResponse`.
- `404 Not Found` — no simulation is active.

### `DELETE /api/v1/simulation`

Stop and remove the active simulation. The MCP server is torn down and all
session state is discarded.

```bash
curl -sS -X DELETE "$BASE/api/v1/simulation" -o /dev/null -w "%{http_code}\n"
```

- `204 No Content` — deleted.
- `404 Not Found` — no simulation is active.

### `POST /api/v1/simulation/reset`

Reset session counters (`tool_call_count`, `queue_depth`, idle timer) of the
active simulation without tearing it down. Use this between test runs against
the same simulated API.

```bash
curl -sS -X POST "$BASE/api/v1/simulation/reset"
```

- `200 OK` — `{"message": "Session reset successfully"}`.
- `404 Not Found` — no simulation is active.
- `503 Service Unavailable` with `Retry-After: 2` — simulation exists but is not yet `ready`.

### `GET /api/v1/simulation/tools`

Return the MCP tool schemas for the active simulation as plain JSON, without
needing an MCP client.

```bash
curl -sS "$BASE/api/v1/simulation/tools"
```

- `200 OK` — array of `{name, description, inputSchema}` objects.
- `404 Not Found` — no simulation is active.
- `503 Service Unavailable` with `Retry-After: 2` — simulation exists but is not yet `ready`.

### `GET /api/v1/simulation/state`

Return the current state snapshot from the simulation's `StoreRegistry` for a
given thread. This is a debugging aid — it exposes the cross-call coherence
state the agent maintains.

**Query parameters**

| Name | Default | Description |
|---|---|---|
| `thread_id` | `default` | Thread to inspect. Different MCP sessions can use different thread IDs. |

```bash
curl -sS "$BASE/api/v1/simulation/state?thread_id=default"
# {} when there is no state yet, or a map of store name -> entity list
```

- `200 OK` — JSON object (possibly empty).
- `404 Not Found` — no simulation is active.
- `503 Service Unavailable` with `Retry-After: 2` — simulation exists but is not yet `ready`.

### `GET /api/v1/simulation/database`

Return the on-disk `db.json` for the active skill. Distinct from
`/simulation/state`, which returns the in-memory store snapshot.

```bash
curl -sS "$BASE/api/v1/simulation/database"
# {"items": [...], "users": [...]}
```

- `200 OK` — JSON object: the contents of `db.json`.
- `404 Not Found` — no simulation declared.
- `500 Internal Server Error` — skill bundle incomplete (`db.json` missing).
- `503 Service Unavailable` — simulation exists but isn't ready yet.

### `GET /api/v1/simulation/schema`

Return the active skill's `schema.json` (the JSON Schema that
`db.json` is validated against). Read-only. Clients producing payloads
for `PUT /simulation/database` should fetch this first to learn the
expected shape.

```bash
curl -sS "$BASE/api/v1/simulation/schema"
# {"type": "object", "properties": {...}, "$defs": {...}}
```

- `200 OK` — JSON object: the contents of `schema.json`.
- `404 Not Found` — no simulation declared.
- `500 Internal Server Error` — skill bundle incomplete (`schema.json` missing).
- `503 Service Unavailable` — simulation exists but isn't ready yet.

### `PUT /api/v1/simulation/database`

Atomically replace the active skill's `db.json` with the request body
and reset the running simulation so the next `tools/call` reloads
from the new seed.

**Request body** — the full `db.json` document, e.g.
`{"items": [...], "users": [...]}`.

**Behavior**

- Validated against the active skill's `schema.json` before the write.
  Validation failures return `422` and the file on disk is unchanged.
- The write is atomic (temp file + rename).
- On success, the agent thread and in-memory stores are reset. The
  conversation history is dropped.
- Refuses with `409` while tool calls are in flight; retry once they drain.

**Out-of-band edits.** While a simulation is active the harness owns
`skills-store/<name>/db.json`. Editing the file directly is not supported —
changes will not be picked up until a `PUT` (which replaces the file and
triggers a reset) or a delete-and-recreate cycle.

```bash
curl -sS -X PUT "$BASE/api/v1/simulation/database" \
  -H "Content-Type: application/json" \
  -d '{"items": [{"id": "1", "name": "Bistro"}]}'
# {"message": "Database replaced; simulation reset"}
```

- `200 OK` — `{"message": "Database replaced; simulation reset"}`.
- `404 Not Found` — no simulation declared.
- `409 Conflict` — tool calls in flight (`{"detail": ..., "queue_depth": N}`).
- `422 Unprocessable Content` — body does not validate (`{"detail": ..., "json_path": "..."}`).
- `503 Service Unavailable` — simulation exists but isn't ready yet.

### Health and probe endpoints

| Path | Purpose | Response |
|---|---|---|
| `GET /health` | Generic liveness check. | `200 {"status":"healthy"}` |
| `GET /healthz` | Kubernetes liveness probe. Returns 200 once the process is up. | `200 {"status":"ok"}` |
| `GET /readyz` | Kubernetes readiness probe. Returns 503 while draining on shutdown, or if a configured `startup.autostart_simulation` failed to start on boot. | `200 {"status":"ready"}` or `503 {"status":"draining"}` |

## MCP transport

The MCP transport is fixed at startup by `mcp.transport` in `harness.yaml`.
Both transports expose identical `tools/list` and `tools/call` semantics — the
choice is purely about how messages are framed on the wire.

All MCP endpoints require a simulation that is fully `ready`. Calling them
before `POST /api/v1/simulation`, or while the simulation is still initializing,
returns HTTP `503 Service Unavailable` with a `Retry-After: 2` header. The body
shape depends on the failure reason:

```json
{
  "error": "No simulation active",
  "message": "Create a simulation via POST /api/v1/simulation first"
}
```

or, when a simulation exists but has not finished initializing:

```json
{
  "error": "Simulation not ready",
  "message": "Simulation is still initializing. Poll GET /api/v1/simulation until status is 'ready'."
}
```

### SSE transport (default)

Two endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/mcp/sse` | Open a long-lived Server-Sent Events stream that carries MCP protocol messages. Keep open for the duration of the session. |
| `POST` | `/mcp/messages` | Send a single MCP protocol message over the SSE transport. |

The Python MCP SDK handles both legs:

```python
from mcp import ClientSession
from mcp.client.sse import sse_client

async with sse_client("http://localhost:8086/mcp/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        await session.list_tools()
        await session.call_tool("listPets", {})
```

### Streamable HTTP transport

A single endpoint:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/mcp` | Each request carries one complete MCP message; the response streams the reply. |

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async with streamablehttp_client("http://localhost:8086/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        await session.call_tool("listPets", {})
```

### Sidecar port

If the create request supplied `mcp_port`, the MCP server runs on that port
instead of being mounted on the harness app. The `mcp_url` returned by
`POST /api/v1/simulation` reflects this — point your MCP client at it directly.

## Errors

REST errors return JSON of the shape `{"detail": "<message>"}`. Domain
exceptions are mapped by handlers in `main.py`:

| Domain error | HTTP | When it fires |
|---|---|---|
| `SimulationAlreadyExistsError` | `409` | `POST /simulation` while one is already active. |
| `PortInUseError` | `409` | The `mcp_port` requested at create time is bound by another process. |
| `SimulationNotFoundError` | `404` | Operations on a non-existent simulation. |
| `SimulationArtifactsNotFoundError` | `404` | `POST /simulation/start` for a name with no complete baked artifacts. Response body includes `name` and the `missing` files. |
| `SimulationNotReadyError` | `503` | Calling tools/state/reset or MCP transports while simulation status is not yet `ready`. Response includes `Retry-After: 2`. |
| `OpenAPIValidationError` | `422` | The submitted spec failed OpenAPI 3.x validation. |
| `SessionExpiredError` | `410` | Session exceeded `max_messages` or `idle_timeout_seconds`. |
| `ConcurrentQueueFullError` | `503` | Too many concurrent tool calls (`>= max_queue_depth` already queued). |
| Anything else | `500` | Unexpected. The actual exception is logged but not exposed in the response. |

Examples:

```http
HTTP/1.1 409 Conflict
content-type: application/json

{"detail": "A simulation is already active. Delete it first or pass regenerate_skill=true."}
```

```http
HTTP/1.1 422 Unprocessable Entity
content-type: application/json

{"detail": "OpenAPI validation failed: 'paths' is a required property"}
```

```http
HTTP/1.1 410 Gone
content-type: application/json

{"detail": "Session expired: max_messages_exceeded (limit=100, observed=101)"}
```

```http
HTTP/1.1 503 Service Unavailable
content-type: application/json

{"detail": "Concurrent queue full (depth=8, max=8)"}
```

### MCP `tools/call` errors

Errors raised inside a tool call are surfaced through the MCP protocol's
`isError` flag rather than as HTTP errors — the HTTP/SSE transport itself is
healthy. Every error `CallToolResult` contains **two content blocks**: a
human-readable text message followed by a structured JSON payload:

```json
{
  "isError": true,
  "content": [
    {"type": "text", "text": "Session expired: max_messages_exceeded (limit=100, observed=101)"},
    {"type": "text", "text": "{\"reason\": \"session_expired\", \"limit\": 100, \"observed\": 101}"}
  ]
}
```

The last content block is always the structured JSON payload. Stable reason
codes and their extra fields:

| `reason` | Trigger | Extra fields |
|---|---|---|
| `session_expired` | Session limit reached | `limit`, `observed` |
| `concurrent_queue_full` | Queue depth exceeded | — |
| `tool_execution_failed` | Simulated tool returned a failure | — |

For `session_expired`, recover with `POST /api/v1/simulation/reset`. For
`concurrent_queue_full`, back off and retry. For `tool_execution_failed`, the
session counter is **not** advanced and the agent thread is preserved.

Truly unexpected exceptions inside a tool call are not wrapped — they bubble
through the MCP SDK's standard error path.

## Session lifecycle

A simulation runs a single agent thread that accumulates context across every
`tools/call`. The harness enforces three exit conditions:

| Condition | Source | Effect |
|---|---|---|
| Tool-call count reaches `max_messages` | `sessions.max_messages` in `harness.yaml` (default `100`) | Subsequent calls raise `SessionExpiredError`. |
| Idle longer than `idle_timeout_seconds` | `sessions.idle_timeout_seconds` (default `3600`) | Same as above. |
| Explicit reset | `POST /api/v1/simulation/reset` | Counters and agent thread are cleared; the simulation stays up. |

Concurrent `tools/call` invocations are serialised through a bounded FIFO
queue. If `queue_depth >= max_queue_depth` (default `8`) when a call arrives,
the call is rejected with `ConcurrentQueueFullError` rather than queued
indefinitely.

Failed tool calls preserve thread state — only successful calls advance
`tool_call_count`. This means a flaky simulated operation does not drain the
session budget.

`DELETE /api/v1/simulation` discards everything — counters, queue, agent
thread, and the MCP server itself. After delete, a fresh `POST` starts from
zero (and may reuse the cached skill on disk unless `regenerate_skill: true`).
