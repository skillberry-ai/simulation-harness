#!/usr/bin/env bash
#
# check-generation-determinism.sh — verify that repeated generation of one
# spec yields the same runtime contract.
#
# The guarantee under test is contract stability, not byte reproducibility:
# the collection set, each collection's primary key, and manifest.json's
# identity.provenance map must be identical across runs. Field prose may
# differ, so this compares a normalized projection of schema.json +
# manifest.json rather than either file's bytes.
#
# Assumes a harness is already running (start it yourself, on a free port --
# ports 8086-8090 are typically occupied by other people's instances). This
# script never starts, stops, or signals a harness process, and it never uses
# `pkill -f simulation_harness` or any other pattern-matched kill -- that
# pattern matches other users' containerized instances on 8086-8090 and has
# already killed five of them once in this project. If you started a harness
# for this check, tear it down yourself by the PID you recorded.
#
# The harness must also have been *started* with HARNESS_LLM_NO_CACHE set to a
# truthy value, so that every generation call bypasses the shared LiteLLM
# gateway's whole-response cache (see build_chat in
# src/simulation_harness/skills/generation/llm.py). A cached response makes
# repeated identical generations look deterministic when they are not, which
# would make this check pass for the wrong reason. Because the harness reads
# that variable once per LLM call from its own process environment, setting it
# in this script's shell has no effect on an already-running harness -- the
# harness process itself must be restarted with it set.
#
# Usage:
#   scripts/check-generation-determinism.sh <openapi-spec.json> [skill-name]
#
# Env:
#   BASE_URL                  harness base URL (default http://127.0.0.1:8099)
#   SKILLS_DIR                skills folder the harness writes into (default ./skills-store)
#   RUNS                      number of generations to compare (default 5)
#   GENERATE_TIMEOUT_SECONDS  per-run poll timeout (default 300)
#   POLL_INTERVAL_SECONDS     poll interval while waiting for a run (default 3)
set -euo pipefail

# Resolve the spec argument against the caller's cwd *before* the `cd
# "$REPO_ROOT"` below -- otherwise a relative path (the natural way to invoke
# this script, e.g. from a checkout of a spec repo) would silently resolve
# against the repo root instead of where the caller actually is.
SPEC_ARG="${1:-}"
NAME="${2:-determinism-probe}"
SPEC=""
if [[ -n "$SPEC_ARG" ]]; then
  if [[ "$SPEC_ARG" = /* ]]; then
    SPEC="$SPEC_ARG"
  else
    SPEC="$PWD/$SPEC_ARG"
  fi
fi

# Anchor on the script's own location, not `git rev-parse --show-toplevel` --
# the latter depends on the *caller's* cwd, so invoking this script (with a
# relative spec path) from inside a different git repo would cd into that
# repo's root instead of this one, and from a non-git directory would die on
# a raw `git` error. This script lives at scripts/<this file>, so its parent
# directory is the repo root.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
if [[ ! -f "$REPO_ROOT/src/simulation_harness/skills/generation/llm.py" ]]; then
  echo "FAIL: could not find simulation-harness's source tree above this script." >&2
  echo "Expected $REPO_ROOT/src/simulation_harness/skills/generation/llm.py to exist." >&2
  echo "Run this script from its own checkout (scripts/$(basename "$0")), not a copy." >&2
  exit 1
fi
cd "$REPO_ROOT"

BASE_URL="${BASE_URL:-http://127.0.0.1:8099}"
SKILLS_DIR="${SKILLS_DIR:-./skills-store}"
RUNS="${RUNS:-5}"
GENERATE_TIMEOUT_SECONDS="${GENERATE_TIMEOUT_SECONDS:-300}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-3}"

if [[ -z "$SPEC" || ! -f "$SPEC" ]]; then
  echo "usage: $0 <openapi-spec.json> [skill-name]" >&2
  echo "  env: BASE_URL (default $BASE_URL), RUNS (default $RUNS)," >&2
  echo "       SKILLS_DIR (default $SKILLS_DIR)," >&2
  echo "       GENERATE_TIMEOUT_SECONDS (default $GENERATE_TIMEOUT_SECONDS)," >&2
  echo "       POLL_INTERVAL_SECONDS (default $POLL_INTERVAL_SECONDS)" >&2
  exit 2
fi

if ! curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
  echo "FAIL: no harness reachable at $BASE_URL/health" >&2
  echo "Start one yourself on a free port first; 8086-8090 are usually taken." >&2
  exit 1
fi

# The cache-bypass capability has to be BUILT (build_chat, llm.py), not just
# asserted; a grep for a string the code never contains would exit 1 before
# doing any work. Check the mechanism exists...
if ! grep -q "HARNESS_LLM_NO_CACHE" src/simulation_harness/skills/generation/llm.py; then
  echo "FAIL: HARNESS_LLM_NO_CACHE cache-bypass hook not found in llm.py." >&2
  echo "The LiteLLM gateway caches whole responses; without the bypass this" >&2
  echo "check reports determinism it did not measure." >&2
  exit 1
fi

# ...and that this shell has been told the harness was started with it set.
# This is a caller-honesty check, not proof: the variable must have been in
# the *harness process's* environment at startup for build_chat to see it, and
# there is no way for this script to inspect another process's environment.
# Never print the value -- secrets reach this process via the environment too.
_no_cache_set=0
case "${HARNESS_LLM_NO_CACHE:-}" in
  [1Tt][Rr][Uu][Ee] | 1 | [Yy][Ee][Ss]) _no_cache_set=1 ;;
esac
if [[ "$_no_cache_set" -ne 1 ]]; then
  echo "FAIL: HARNESS_LLM_NO_CACHE is not set to a truthy value in this shell." >&2
  echo "Restart the harness with HARNESS_LLM_NO_CACHE=1 set (config and the" >&2
  echo "chat clients are built at startup) before running this check, then" >&2
  echo "export the same variable here so this script knows to expect it." >&2
  exit 1
fi
export HARNESS_LLM_NO_CACHE

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# Seconds-resolution mtime, GNU coreutils then BSD/macOS. Second granularity is
# ample: a real generation takes tens of seconds, a reuse takes about one.
_mtime() {
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0
}

# Runs are strictly sequential: the shared gateway stalls mid-stream at 5+
# concurrent long generations.
for run in $(seq 1 "$RUNS"); do
  echo "--- run $run/$RUNS"

  # Delete any existing (or in-flight) simulation record first. POST is not
  # idempotent -- a record left over from the previous run (or from reset,
  # which does not remove the record) makes run 2's POST fail with 409. DELETE
  # tolerates 404: there is nothing to delete on run 1.
  delete_status="$(curl -sS -o "$workdir/delete-$run.json" -w '%{http_code}' \
    -X DELETE "$BASE_URL/api/v1/simulation")"
  if [[ "$delete_status" != "204" && "$delete_status" != "404" ]]; then
    echo "FAIL: DELETE /api/v1/simulation returned $delete_status on run $run:" >&2
    cat "$workdir/delete-$run.json" >&2
    exit 1
  fi

  # A reused skill is never rewritten, so an unchanged mtime is the signal that
  # this run generated nothing. Captured before the POST; asserted after ready.
  schema="$SKILLS_DIR/$NAME/schema.json"
  mtime_before=0
  if [[ -f "$schema" ]]; then
    mtime_before="$(_mtime "$schema")"
  fi

  # Written to a file and sent with --data-binary @file rather than as an
  # inline -d argument: a real spec's body can run into the hundreds of KB
  # (e.g. booking-com), and some shells/exec paths choke on an argument that
  # large well before the kernel's actual ARG_MAX.
  #
  # The flag is `regenerate_skill`, matching CreateSimulationRequest. Getting
  # this name wrong is silent: the request model declares no `model_config`, so
  # pydantic's default extra="ignore" drops an unknown key and leaves
  # regenerate_skill=False -- runs 2..N then reuse run 1's artifacts and this
  # check passes without ever generating a second time. The mtime guard below
  # exists to make that failure loud if the name ever drifts again.
  jq -n \
    --arg name "$NAME" \
    --slurpfile spec "$SPEC" \
    '{name: $name, openapi_spec: $spec[0], regenerate_skill: true}' \
    >"$workdir/payload-$run.json"
  curl -fsS -X POST "$BASE_URL/api/v1/simulation" \
    -H 'Content-Type: application/json' \
    --data-binary "@$workdir/payload-$run.json" >"$workdir/create-$run.json"

  # POST /api/v1/simulation is 202/async: it returns before generation
  # finishes. Poll GET until the record reaches a terminal status, bounded by
  # a timeout -- a determinism check that silently compares stale or
  # half-written artifacts is worse than one that crashes.
  deadline=$((SECONDS + GENERATE_TIMEOUT_SECONDS))
  phase=""
  while true; do
    get_status="$(curl -sS -o "$workdir/status-$run.json" -w '%{http_code}' \
      "$BASE_URL/api/v1/simulation")"
    if [[ "$get_status" != "200" ]]; then
      echo "FAIL: GET /api/v1/simulation returned $get_status on run $run:" >&2
      cat "$workdir/status-$run.json" >&2
      exit 1
    fi
    phase="$(jq -r '.status' "$workdir/status-$run.json")"
    if [[ "$phase" == "ready" || "$phase" == "failed" ]]; then
      break
    fi
    if (( SECONDS >= deadline )); then
      echo "FAIL: run $run did not reach ready/failed within ${GENERATE_TIMEOUT_SECONDS}s" >&2
      echo "last status: $phase" >&2
      cat "$workdir/status-$run.json" >&2
      exit 1
    fi
    sleep "$POLL_INTERVAL_SECONDS"
  done
  if [[ "$phase" == "failed" ]]; then
    echo "FAIL: generation failed on run $run:" >&2
    jq -c '.error' "$workdir/status-$run.json" >&2
    exit 1
  fi

  manifest="$SKILLS_DIR/$NAME/manifest.json"
  if [[ ! -f "$schema" ]]; then
    echo "FAIL: $schema not written on run $run" >&2
    exit 1
  fi
  # Reuse guard. Deliberately not a duration threshold: those need a
  # per-spec/per-model constant and go stale. If the artifact was not rewritten,
  # the harness served a cached skill and there is nothing to compare.
  mtime_after="$(_mtime "$schema")"
  if [[ "$mtime_before" != "0" && "$mtime_after" == "$mtime_before" ]]; then
    echo "FAIL: run $run did not rewrite $schema (mtime unchanged) -- the" >&2
    echo "harness reused the existing skill instead of regenerating, so this" >&2
    echo "check would compare run 1's artifacts against themselves. Verify the" >&2
    echo "create payload's regenerate flag still matches the field name on" >&2
    echo "CreateSimulationRequest (src/simulation_harness/models/requests.py)." >&2
    exit 1
  fi
  if [[ ! -f "$manifest" ]]; then
    echo "FAIL: $manifest not written on run $run (needed to compare identity.provenance)" >&2
    exit 1
  fi

  # The contract projection: collection names with each one's primary key as
  # the runtime resolves it (properties -> items.$ref -> $defs.x-primary-key),
  # plus manifest.json's identity.provenance. Provenance is part of the
  # comparison because a run that silently took the LLM fallback for an entity
  # is exactly the case where contract stability is not guaranteed -- this
  # should surface that, not average over it. Done in Python rather than jq
  # because chasing $ref through $defs in jq is write-only.
  uv run python - "$schema" "$manifest" >"$workdir/contract-$run.json" <<'PY'
import json, sys

schema = json.load(open(sys.argv[1]))
manifest = json.load(open(sys.argv[2]))

defs = schema.get("$defs", {})
contract = {}
for collection, prop in sorted(schema.get("properties", {}).items()):
    ref = (prop.get("items") or {}).get("$ref", "")
    entity = defs.get(ref.split("/")[-1], {}) if ref.startswith("#/$defs/") else {}
    contract[collection] = entity.get("x-primary-key")

provenance = manifest.get("identity", {}).get("provenance", {})

json.dump(
    {"contract": contract, "provenance": dict(sorted(provenance.items()))},
    sys.stdout,
    indent=2,
    sort_keys=True,
)
PY
  echo "contract: $(tr -d '\n ' <"$workdir/contract-$run.json")"
done

status=0
for run in $(seq 2 "$RUNS"); do
  if ! diff -q "$workdir/contract-1.json" "$workdir/contract-$run.json" >/dev/null; then
    echo "FAIL: run $run's contract differs from run 1:" >&2
    diff -u "$workdir/contract-1.json" "$workdir/contract-$run.json" >&2 || true
    status=1
  fi
done

if [[ "$status" -eq 0 ]]; then
  echo "PASS: $RUNS runs produced an identical contract"
else
  echo "A drifting collection tagged \"llm\" in identity.provenance is the" >&2
  echo "known residual risk (the LLM fallback is not deterministic), not a" >&2
  echo "bug in this check. A drifting collection tagged \"derived\" is a bug." >&2
fi
exit "$status"
