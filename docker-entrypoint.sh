#!/bin/sh
set -e

if [ "$(id -u)" = "0" ]; then
    # Running as root (e.g. plain `docker run`): on Docker Desktop / WSL2,
    # bind-mounted host directories appear as root-owned inside the container
    # regardless of host ownership. chown the writable volume dirs before
    # dropping to the harness user so the app can write its logs and skill
    # files, then step down to the unprivileged harness user.
    chown harness:harness /app/logs /app/skills-store 2>/dev/null || true
    exec gosu harness "$@"
fi

# Already non-root (e.g. Kubernetes runAsUser:1000 == harness): gosu cannot
# drop privileges without root/CAP_SETUID, and the switch is redundant since
# we are already the intended user. Any mounted volume must be writable by the
# runtime UID (set fsGroup on the pod securityContext).
exec "$@"
