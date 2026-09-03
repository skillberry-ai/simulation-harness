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
| `latest`      | git tag `vX.Y.Z`  | `latest`      | ❌ moving                  |

**Pin by digest in production.** A tag is a mutable pointer; a digest is the
immutable content hash of the exact build. Every non-PR CI run prints the full
`...@sha256:...` reference to its **workflow run summary** (for the multi-arch
build this is the manifest-index digest covering both arches). Consume that:

```
ghcr.io/<owner>/simulation-harness@sha256:<digest>
```

At minimum pin an immutable `X.Y.Z` release tag; never deploy `latest` or `main`
to a cluster.

`latest` follows the newest **release**, not `main` — it is what a bare
`docker pull` resolves to, so it never serves unreleased trunk. It is still a
moving pointer, so it is not something to pin. Track trunk with `main`.
Pre-release tags (`v0.3.0-rc1`) publish only their exact version and move neither
`latest` nor a `X.Y` line.

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
| `HARNESS_LLM_PROVIDER`                         | `llm.provider`                              |
| `HARNESS_LLM_SKILL_GENERATION_MODEL`           | `llm.skill_generation_model`                |
| `HARNESS_LLM_SIMULATION_MODEL`                 | `llm.simulation_model`                      |
| `HARNESS_SERVER_HOST`                          | `server.host`                               |
| `HARNESS_SERVER_PORT`                          | `server.port`                               |
| `HARNESS_SKILLS_FOLDER`                        | `skills.folder`                             |
| `HARNESS_AUTOSTART_ENABLED`                    | `startup.autostart_enabled` (`true`/`false`)|
| `HARNESS_AUTOSTART_SIMULATION`                 | `startup.autostart_simulation`              |
| `HARNESS_LOG_LEVEL`                            | `logging.level`                             |
| `HARNESS_LOG_DESTINATION`                      | `logging.destination_folder`                |
| `HARNESS_MCP_TRANSPORT`                        | `mcp.transport` (`sse` or `streamable_http`)|
| `HARNESS_SESSIONS_MAX_MESSAGES`                | `sessions.max_messages`                     |
| `HARNESS_SESSIONS_IDLE_TIMEOUT_SECONDS`        | `sessions.idle_timeout_seconds`             |
| `HARNESS_SESSIONS_MAX_CONCURRENT_QUEUE_DEPTH`  | `sessions.max_concurrent_queue_depth`       |

Secrets (`LLM_API_KEY`, optional `LLM_API_BASE`) come from `harness-secrets` Secret.

## LLM model & provider config

The four LLM settings a consumer typically tunes split across **two** channels:

| Setting | Channel | How to set it |
|---|---|---|
| `LLM_API_KEY`            | `harness-secrets` **Secret** (`secret.yaml`) | env var, injected via `envFrom` |
| `LLM_API_BASE` (optional)| `harness-secrets` **Secret** (`secret.yaml`) | env var, injected via `envFrom` |
| `skill_generation_model` | `harness-config` **ConfigMap** (`harness.yaml`) | edit the `llm:` block, or set `HARNESS_LLM_SKILL_GENERATION_MODEL` |
| `simulation_model`       | `harness-config` **ConfigMap** (`harness.yaml`) | edit the `llm:` block, or set `HARNESS_LLM_SIMULATION_MODEL` |

The API key/base are read only from the process environment (never from YAML),
so they belong in the Secret. The model names have two channels: the `llm:` block
in the ConfigMap, and the `HARNESS_LLM_*` env vars in the override table above
(env wins). Prefer the ConfigMap when you own the manifests; the env vars exist
for orchestrators that deploy this image **without** mounting a `harness.yaml`,
where the ConfigMap route isn't available and the baked-in defaults would
otherwise be the only reachable models.

If you override the model, consider `HARNESS_LLM_PROVIDER` too — `provider` and
the model prefix must stay consistent with the endpoint `LLM_API_BASE` points at.

Edit the `llm:` block in `deploy/k8s/configmap.yaml`:

```yaml
data:
  harness.yaml: |
    llm:
      provider: openai                  # provider family
      skill_generation_model: gpt-4.1   # one-time, per-spec skill generation
      simulation_model: gpt-4.1         # hot path — every tools/call
      temperature: 0
    # ...
```

Model ids are passed **verbatim** as the `model` field to the OpenAI-compatible
endpoint `LLM_API_BASE` points at (default: `api.openai.com`), so use a bare id
such as `gpt-4.1` — not a prefixed `openai/gpt-4.1`. If you route through a
gateway that namespaces models (e.g. `azure/…` on a LiteLLM proxy), use whatever
name that gateway expects. The two models are independent — e.g. a larger model
for generation and a cheaper one for the simulation hot path.

Note that every generation call sends an explicit `temperature` (see the
`generation:` block), so OpenAI reasoning models that accept only the default
temperature are not drop-in replacements here.

**Config is read once at startup.** Editing the ConfigMap (or rotating the
Secret) has no effect on a running pod. Trigger a restart to pick up changes:

```bash
kubectl -n simulation-harness rollout restart deploy/simulation-harness
```

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
