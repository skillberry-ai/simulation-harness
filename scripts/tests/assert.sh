#!/usr/bin/env bash
#
# assert.sh — minimal assertion helpers for the scripts/ test suite.
# Sourced by scripts/tests/test-*.sh. Not executable on its own.
# Sourced-only: deliberately sets no shell options, since that would affect
# the caller's shell.

ASSERT_FAILURES=0
ASSERT_CHECKS=0

_assert_pass() {
    ASSERT_CHECKS=$((ASSERT_CHECKS + 1))
    printf '  \033[32mok\033[0m %s\n' "$1"
}

_assert_fail() {
    ASSERT_CHECKS=$((ASSERT_CHECKS + 1))
    ASSERT_FAILURES=$((ASSERT_FAILURES + 1))
    printf '  \033[31mFAIL\033[0m %s\n' "$1"
    shift
    printf '       %s\n' "$@"
}

assert_eq() {
    local label="$1" actual="$2" expected="$3"
    if [[ "$actual" == "$expected" ]]; then
        _assert_pass "$label"
    else
        _assert_fail "$label" "expected: [$expected]" "actual:   [$actual]"
    fi
}

assert_contains() {
    local label="$1" haystack="$2" needle="$3"
    if [[ "$haystack" == *"$needle"* ]]; then
        _assert_pass "$label"
    else
        _assert_fail "$label" "expected to contain: [$needle]" "actual:              [$haystack]"
    fi
}

assert_empty() {
    local label="$1" actual="$2"
    if [[ -z "$actual" ]]; then
        _assert_pass "$label"
    else
        _assert_fail "$label" "expected empty" "actual: [$actual]"
    fi
}

# assert_fails <label> <command...> — asserts the command exits non-zero.
assert_fails() {
    local label="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        _assert_fail "$label" "expected non-zero exit from: $*"
    else
        _assert_pass "$label"
    fi
}

assert_summary() {
    printf '\n%s check(s), %s failure(s)\n' "$ASSERT_CHECKS" "$ASSERT_FAILURES"
    if (( ASSERT_FAILURES > 0 )); then
        return 1
    fi
    return 0
}
