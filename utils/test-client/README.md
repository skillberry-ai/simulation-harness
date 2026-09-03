# Harness Test Client (PatternFly)

A React + PatternFly single-page console for exercising the simulation harness, backed by a thin Node/Express proxy. One process, one port in production.

## Requirements

- Node 20 LTS (`.nvmrc`). `nvm use` to match.
- `pnpm` (recommended) or `npm` — the Makefile auto-detects.

## Quick start

```bash
cd utils/test-client
make setup            # install dependencies
make dev              # client on :5173 (proxies /proxy/* to the Express server on :3000)
```

Open http://localhost:5173. Set the harness URL in the masthead (default `http://localhost:8086`) and click **Test connection**.

## Production-style run

```bash
make build
make start            # serves the built SPA + proxy on :3000 (PID in .test-client.pid)
make stop
```

## Configuration (proxy only)

Copy `.env.example` to `.env`:

- `HARNESS_URL` — upstream harness (default `http://localhost:8086`). The masthead URL field overrides this per request via the `X-Harness-Url` header.
- `PORT` — proxy/prod port (default `3000`).
- `MCP_TRANSPORT` — `sse` (default) or `streamable-http`; must match the harness's `mcp.transport`.
- `HARNESS_URL_ALLOWLIST` — comma-separated origins the `X-Harness-Url` header may target, beyond the `HARNESS_URL` origin. See below.
- `RATE_LIMIT_WINDOW_MS` / `RATE_LIMIT_MAX` — request rate limit (default 600 requests per 60 s). Generous because the harness itself has a 10-minute REST timeout. Applied as two independent counters: one for the `/proxy` routes, one for the static asset and SPA-fallback routes, so loading the UI cannot exhaust the proxy budget.

### Retargeting the harness

Because `X-Harness-Url` reaches the proxy from the browser, it is attacker-controllable
and would otherwise be a server-side request forgery primitive. The proxy therefore
only forwards to:

- **loopback**, on any port — `localhost`, `127.0.0.1`, `[::1]` — so the default local
  workflow and the masthead port field need no configuration;
- the origin of `HARNESS_URL`;
- any origin listed in `HARNESS_URL_ALLOWLIST`.

Anything else — a remote host, or a non-`http(s)` scheme — gets `400
harness_url_not_allowed`, and no upstream request is made. To point the masthead at a
remote harness, add its origin explicitly:

```bash
HARNESS_URL_ALLOWLIST=https://harness.staging.example:8443
```

Note that an origin is scheme + host + port, so a different port on an allowlisted host
is a separate entry.

The header selects one of those permitted bases; it never builds the upstream URL. Only
the origin is honoured, so any path, query or fragment in `X-Harness-Url` is discarded —
`http://localhost:8086/x` targets `http://localhost:8086`, not `http://localhost:8086/x`.
If your harness is served under a base path, put it in `HARNESS_URL`, which is used
verbatim.

## Testing

```bash
make test             # Vitest (client RTL + server) once
make test-watch
make lint
```

## Layout

- `client/` — React + Vite SPA (PatternFly).
- `server/` — Express proxy (REST passthrough + MCP bridge via `@modelcontextprotocol/sdk`).
- `tests/` — client Vitest + RTL; `tests/mocks/` shared MSW fixtures. Server tests live in `server/tests/`.
- `examples/` — sample OpenAPI specs.
