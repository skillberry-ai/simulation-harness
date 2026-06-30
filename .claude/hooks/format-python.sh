#!/usr/bin/env bash
# PostToolUse hook: auto-format and autofix Python files after an agent edits them.
# Receives the tool-call payload as JSON on stdin; we pull out the edited path.
# Always exits 0 so a formatting hiccup never blocks the agent.
set -uo pipefail

payload="$(cat)"
file="$(printf '%s' "$payload" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("file_path",""))' 2>/dev/null || true)"

case "$file" in
  *.py)
    [ -f "$file" ] || exit 0
    uv run ruff format "$file" >/dev/null 2>&1 || true
    uv run ruff check --fix "$file" >/dev/null 2>&1 || true
    ;;
esac
exit 0
