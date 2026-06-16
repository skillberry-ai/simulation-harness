#!/bin/sh
set -e

# On Docker Desktop / WSL2, bind-mounted host directories appear as root-owned
# inside the container regardless of host ownership. chown the writable volume
# dirs before dropping to the harness user so the app can write its logs and
# skill files.
chown harness:harness /app/logs /app/skills-store 2>/dev/null || true

exec gosu harness "$@"
