# syntax=docker/dockerfile:1.7

# ---------- builder ----------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_INSTALLER_METADATA=1

# uv 0.5+ — pin a minor for reproducibility.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /build

# Cache deps before copying the rest of the project.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-install-project --no-editable

COPY src ./src
COPY README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-editable

# ---------- runtime ----------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    HARNESS_CONFIG_PATH=/app/config/harness.yaml \
    HARNESS_LOG_DESTINATION=/app/logs \
    HARNESS_SKILLS_FOLDER=/app/skills-store

# Non-root user
RUN groupadd -r harness --gid=1000 \
 && useradd -r -g harness --uid=1000 --home-dir=/app --shell=/sbin/nologin harness

# gosu for entrypoint privilege drop (chown volume dirs then exec as harness)
RUN apt-get update \
 && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy resolved venv from builder.
COPY --from=builder --chown=harness:harness /build/.venv /app/.venv

# Copy app code + default config.
COPY --chown=harness:harness src /app/src
COPY --chown=harness:harness config /app/config

# Mountable, writable dirs (k8s will mount real volumes here in prod).
RUN mkdir -p /app/logs /app/skills-store \
 && chown -R harness:harness /app

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8086

# liveness check matches /healthz (Docker, not k8s — k8s uses its own probes).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8086/healthz', timeout=3).status==200 else 1)"

# Entrypoint runs as root to fix volume dir ownership, then drops to harness.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "simulation_harness"]
