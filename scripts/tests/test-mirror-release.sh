#!/usr/bin/env bash
#
# Offline end-to-end test for scripts/mirror-release.sh. Builds a fixture
# source repo and a bare target, mirrors two releases into it, and asserts the
# published ref shape.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/tests/assert.sh
source "$SCRIPT_DIR/assert.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/test-mirror.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

SRC="$WORK/source"
TGT="$WORK/target.git"

echo "test-mirror-release.sh"

# --- fixture source: two releases, a feature branch, a non-release tag ------
git init -q -b main "$SRC"
git -C "$SRC" config user.email "test@example.com"
git -C "$SRC" config user.name "Test"
git -C "$SRC" config commit.gpgsign false
git -C "$SRC" config tag.gpgsign false

printf '# Fixture\n\nOriginal readme body.\n' > "$SRC/README.md"
git -C "$SRC" add README.md
git -C "$SRC" commit -q -m "chore: initial"
git -C "$SRC" tag -a v0.1.0 -m "Release v0.1.0"
V010="$(git -C "$SRC" rev-parse "v0.1.0^{commit}")"

git -C "$SRC" commit -q --allow-empty -m "feat: second release content"
git -C "$SRC" tag -a v0.2.0 -m "Release v0.2.0"
V020="$(git -C "$SRC" rev-parse "v0.2.0^{commit}")"

git -C "$SRC" tag -a not-a-release -m "should be pruned"
git -C "$SRC" branch feat/in-progress
git -C "$SRC" commit -q --allow-empty -m "chore: unreleased work on main"

git init -q --bare -b main "$TGT"

mirror() {
    SOURCE="$SRC" TARGET="$TGT" CLONE_DIR="$WORK/unused" \
        "$REPO_ROOT/scripts/mirror-release.sh" --no-release-page --no-reset-local "$@" 2>&1
}

# --- dry run writes nothing ------------------------------------------------
out="$(mirror --dry-run v0.1.0)"
assert_contains "dry run names the release" "$out" "v0.1.0"
assert_empty "dry run pushes no refs" "$(git -C "$TGT" for-each-ref)"

# --- publish v0.1.0 --------------------------------------------------------
mirror v0.1.0 >/dev/null
assert_eq "target has only main" \
    "$(git -C "$TGT" for-each-ref --format='%(refname)' refs/heads | tr '\n' ' ')" \
    "refs/heads/main "
assert_eq "main's parent is the release commit" \
    "$(git -C "$TGT" rev-parse 'refs/heads/main^')" "$V010"
assert_contains "main is the notice commit" \
    "$(git -C "$TGT" log -1 --format=%s refs/heads/main)" "detached-mirror notice"
readme="$(git -C "$TGT" show refs/heads/main:README.md)"
assert_contains "notice names the release" "$readme" "published from release \`v0.1.0\`"
assert_contains "notice warns about overrides" "$readme" "will be overridden"
assert_contains "original readme body survives" "$readme" "Original readme body."
assert_eq "only release tags are published" \
    "$(git -C "$TGT" tag -l | sort -V | tr '\n' ' ')" "v0.1.0 v0.2.0 "

# --- publish v0.2.0: repoints main, notices do not stack -------------------
mirror v0.2.0 >/dev/null
assert_eq "main's parent is now v0.2.0" \
    "$(git -C "$TGT" rev-parse 'refs/heads/main^')" "$V020"
assert_eq "exactly one notice commit in history" \
    "$(git -C "$TGT" log --format=%s refs/heads/main | grep -c 'detached-mirror notice')" "1"
assert_contains "notice names the new release" \
    "$(git -C "$TGT" show refs/heads/main:README.md)" "published from release \`v0.2.0\`"

# --- default ref resolution ------------------------------------------------
out="$(mirror --dry-run)"
assert_contains "defaults to the highest release tag" "$out" "v0.2.0"

# --- rejections ------------------------------------------------------------
assert_fails "rejects an unknown tag" bash -c \
    "SOURCE='$SRC' TARGET='$TGT' CLONE_DIR='$WORK/unused' \
     '$REPO_ROOT/scripts/mirror-release.sh' --no-release-page --no-reset-local v9.9.9"
assert_fails "rejects a non-release ref" bash -c \
    "SOURCE='$SRC' TARGET='$TGT' CLONE_DIR='$WORK/unused' \
     '$REPO_ROOT/scripts/mirror-release.sh' --no-release-page --no-reset-local not-a-release"
assert_fails "rejects a missing local clone when resetting" bash -c \
    "SOURCE='$SRC' TARGET='$TGT' CLONE_DIR='$WORK/nope' \
     '$REPO_ROOT/scripts/mirror-release.sh' --no-release-page v0.2.0"

assert_summary
