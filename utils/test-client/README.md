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
