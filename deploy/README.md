# Deployment

Containerization assets for the simulation harness.

## Local — `docker run`

```bash
docker build -t simulation-harness:dev .
docker run --rm -p 8086:8086 \
  -e LLM_API_KEY="$LLM_API_KEY" \
  simulation-harness:dev
```

Then `curl http://localhost:8086/healthz`.

## Local — `docker compose`

```bash
LLM_API_KEY=... docker compose up -d
docker compose logs -f harness
docker compose down
```

## Published image & tag policy

CI (`.github/workflows/docker-publish.yml`) builds and publishes **one generic
image** — there is no per-tool build. It is pushed to the GHCR namespace of the
repository (or mirror) that runs the workflow:

```
ghcr.io/<owner>/simulation-harness
```

Tags produced per build:

| Tag           | When              | Example       | Safe to pin in a cluster? |
|---------------|-------------------|---------------|---------------------------|
| `X.Y.Z`       | git tag `vX.Y.Z`  | `0.3.1`       | ✅ immutable by convention |
| `X.Y`         | git tag `vX.Y.Z`  | `0.3`         | ⚠️ moves with patches      |
| `sha-<short>` | every build       | `sha-1a2b3c4` | ✅ ties to one commit      |
| `main`        | push to `main`    | `main`        | ❌ moving                  |
| `latest`      | push to `main`    | `latest`      | ❌ moving                  |

**Pin by digest in production.** A tag is a mutable pointer; a digest is the
immutable content hash of the exact build. Every non-PR CI run prints the full
`...@sha256:...` reference to its **workflow run summary** (for the multi-arch
build this is the manifest-index digest covering both arches). Consume that:

```
ghcr.io/<owner>/simulation-harness@sha256:<digest>
```

At minimum pin an immutable `X.Y.Z` release tag; never deploy `latest` or `main`
to a cluster.

## Kubernetes — Kustomize

1. Build and push the image to a registry your cluster can read:
   ```bash
   docker build -t ghcr.io/your-org/simulation-harness:v0.1.0 .
   docker push ghcr.io/your-org/simulation-harness:v0.1.0
   ```
2. Set the image in `deploy/k8s/kustomization.yaml` (`images:` block).
3. Create the secret:
   ```bash
   cp deploy/k8s/secret.example.yaml deploy/k8s/secret.yaml
   # edit deploy/k8s/secret.yaml — fill in LLM_API_KEY
   kubectl apply -f deploy/k8s/secret.yaml
   ```
4. Apply the bundle:
   ```bash
   kubectl apply -k deploy/k8s/
   ```
5. Verify:
   ```bash
   kubectl -n simulation-harness rollout status deploy/simulation-harness
   kubectl -n simulation-harness port-forward svc/simulation-harness 8086:8086
   curl http://localhost:8086/readyz
   ```

## Probes

| Endpoint  | Purpose       | 200 condition                        | 503 condition       |
|-----------|---------------|--------------------------------------|---------------------|
| `/healthz`| Liveness      | Process is running                   | (never — process down → connection refused) |
| `/readyz` | Readiness     | App is up and not draining           | Lifespan shutdown started |

## Env-var config overrides

These override the values in the mounted `harness.yaml`:

| Variable                                       | Maps to                                     |
|-----------------------------------------------|---------------------------------------------|
| `HARNESS_CONFIG_PATH`                          | path to the YAML file                       |
| `HARNESS_SERVER_HOST`                          | `server.host`                               |
| `HARNESS_SERVER_PORT`                          | `server.port`                               |
| `HARNESS_SKILLS_FOLDER`                        | `skills.folder`                             |
| `HARNESS_LOG_LEVEL`                            | `logging.level`                             |
| `HARNESS_LOG_DESTINATION`                      | `logging.destination_folder`                |
| `HARNESS_MCP_TRANSPORT`                        | `mcp.transport` (`sse` or `streamable_http`)|
| `HARNESS_SESSIONS_MAX_MESSAGES`                | `sessions.max_messages`                     |
| `HARNESS_SESSIONS_IDLE_TIMEOUT_SECONDS`        | `sessions.idle_timeout_seconds`             |
| `HARNESS_SESSIONS_MAX_CONCURRENT_QUEUE_DEPTH`  | `sessions.max_concurrent_queue_depth`       |

Secrets (`LLM_API_KEY`, optional `LLM_API_BASE`) come from `harness-secrets` Secret.

## Graceful shutdown

On `SIGTERM` (rolling update, `kubectl delete`), the lifespan teardown sets
`app.state.draining = True`, so `/readyz` returns 503 and the Service stops
sending new traffic. uvicorn then waits up to `timeout_graceful_shutdown=30s`
for in-flight tool calls before force-closing.

`terminationGracePeriodSeconds: 45` in the Deployment gives uvicorn that
30 s plus some headroom for connection drain.

## Scaling caveat

Each pod owns its own in-memory simulation slot. Running `replicas > 1`
without sticky routing means `POST /api/v1/simulation` lands on whichever
pod the LB picked, and subsequent MCP traffic for that simulation will
404 if it lands elsewhere. The included `hpa.yaml` is therefore opt-in.
