# Kubernetes Secrets

The simulation-harness reads the following secret values from environment
variables. In local development, set them in `.env`. In Kubernetes, deliver
them via a `Secret` resource referenced by `valueFrom.secretKeyRef` in the
pod's `env` block.

| Env var         | Required | Description                              |
|-----------------|----------|------------------------------------------|
| `LLM_API_KEY`   | yes      | API key for the LLM provider             |
| `LLM_API_BASE`  | no       | Optional custom API base URL             |

The application reads secrets exclusively via the `Secrets` class in
`src/simulation_harness/config/secrets.py`. No other code path reads secret
values from the environment.

## Secret resource

Created out of band (kubectl, GitOps, or an operator). Never committed.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: simulation-harness-llm
  namespace: simulation-harness
type: Opaque
stringData:
  api-key: "sk-..."          # required
  api-base: ""               # optional; omit key entirely if unused
```

Conventions:

- One `Secret` resource per logical credential bundle. Future bundles (e.g.
  MCP-server tokens) get their own `Secret`.
- `stringData` for human-authored secrets (auto-base64). Sealed/external-store
  output uses `data`.
- `Secret` name is stable infrastructure. Keys inside the secret are
  `kebab-case`. Env var names exposed to the pod are `SCREAMING_SNAKE_CASE`.

## Deployment env block

```yaml
spec:
  template:
    spec:
      containers:
      - name: simulation-harness
        env:
        - name: LLM_API_KEY
          valueFrom:
            secretKeyRef:
              name: simulation-harness-llm
              key: api-key
        - name: LLM_API_BASE
          valueFrom:
            secretKeyRef:
              name: simulation-harness-llm
              key: api-base
              optional: true
```

Conventions:

- `optional: true` for env vars whose `Secrets` field is `Optional`.
- Explicit `secretKeyRef` per env var rather than `envFrom: secretRef` — the
  contract is auditable from the manifest alone.
- No volume mounts. Env-only delivery.
- Secret rotation requires a pod rollout
  (`kubectl rollout restart deployment/simulation-harness`). Watch-and-reload
  is not implemented.
