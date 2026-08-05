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

# --- a bare X.Y.Z is accepted as well as vX.Y.Z -----------------------------
# `make release VERSION=0.2.0` is bare and `make mirror VERSION=v0.2.0` is
# prefixed; guessing wrong must not cost a retry.
out="$(mirror --dry-run 0.1.0)"
assert_contains "bare X.Y.Z is normalised to vX.Y.Z" "$out" "Release : v0.1.0"

# --- a pre-release tag is not a release ------------------------------------
git -C "$SRC" tag -a v0.3.0-rc1 -m "prerelease"
out="$(mirror --dry-run)"
assert_contains "pre-release tag is not the latest release" "$out" "using the latest: v0.2.0"
assert_fails "pre-release tag is rejected as an explicit ref" bash -c \
    "SOURCE='$SRC' TARGET='$TGT' CLONE_DIR='$WORK/unused' \
     '$REPO_ROOT/scripts/mirror-release.sh' --no-release-page --no-reset-local v0.3.0-rc1"
mirror v0.2.0 >/dev/null
assert_eq "pre-release tag is pruned from the target" \
    "$(git -C "$TGT" tag -l | sort -V | tr '\n' ' ')" "v0.1.0 v0.2.0 "

# --- the -- option terminator ----------------------------------------------
# It used to leave REF empty, so `mirror-release.sh -- v0.1.0` silently
# published the *latest* release — the inverse of the intended rollback.
out="$(mirror -- v0.1.0 || true)"
assert_contains "rejects the -- option terminator" "$out" "unknown option: --"
assert_eq "-- run publishes nothing" \
    "$(git -C "$TGT" rev-parse 'refs/heads/main^')" "$V020"

# --- --yes is accepted (the prompt itself only arms for the default target) --
out="$(mirror --yes v0.2.0)"
assert_eq "--yes runs unattended" \
    "$(git -C "$TGT" rev-parse 'refs/heads/main^')" "$V020"
# No prompt is armed for an overridden target, so --yes must not claim to have
# skipped one.
case "$out" in
    *"--yes given"*) yes_noise=yes ;;
    *)               yes_noise=no ;;
esac
assert_eq "--yes is quiet when no prompt was armed" "$yes_noise" "no"

# --- confirmation before a push to the default target -----------------------
# The prompt only arms when TARGET is the built-in default, which is the real
# public URL — so exercise it against a copy of the script whose built-in
# default is a fixture path. Nothing here can reach a real remote.
CONFIRM_TGT="$WORK/confirm.git"
CONFIRM_SH="$WORK/mirror-confirm.sh"
sed "s|^TARGET_DEFAULT=.*|TARGET_DEFAULT='$CONFIRM_TGT'|" \
    "$REPO_ROOT/scripts/mirror-release.sh" > "$CONFIRM_SH"
chmod +x "$CONFIRM_SH"
assert_eq "the copy's built-in default was rewritten to the fixture" \
    "$(grep -c "^TARGET_DEFAULT='$CONFIRM_TGT'$" "$CONFIRM_SH")" "1"

confirm_cmd() {
    printf "cd '%s' && SOURCE='%s' TARGET='%s' CLONE_DIR='%s' '%s' %s v0.1.0" \
        "$REPO_ROOT" "$SRC" "$CONFIRM_TGT" "$WORK/unused" "$CONFIRM_SH" \
        "--no-release-page --no-reset-local $*"
}
fresh_confirm_target() {
    rm -rf -- "$CONFIRM_TGT"
    git init -q --bare -b main "$CONFIRM_TGT"
}

# Non-interactive: must not prompt, or every automated run would hang.
fresh_confirm_target
out="$(printf '' | bash -c "$(confirm_cmd)" 2>&1)"
assert_contains "no prompt when stdin is not a terminal" "$out" "stdin is not a terminal"
assert_contains "the unattended run still publishes" "$out" "Published v0.1.0"

# Interactive: needs a pty, which script(1) provides. Skipped where it does not.
if script -qec true /dev/null >/dev/null 2>&1; then
    fresh_confirm_target
    out="$(echo "wrong-url" | script -qec "$(confirm_cmd)" /dev/null 2>&1 || true)"
    assert_contains "a terminal run asks for the target URL" "$out" "Type the target URL"
    assert_contains "a mistyped URL aborts" "$out" "confirmation did not match"
    assert_empty "the aborted run pushed nothing" "$(git -C "$CONFIRM_TGT" for-each-ref)"

    out="$(echo "$CONFIRM_TGT" | script -qec "$(confirm_cmd)" /dev/null 2>&1)"
    assert_contains "typing the target URL proceeds" "$out" "Published v0.1.0"

    fresh_confirm_target
    out="$(printf '\n' | script -qec "$(confirm_cmd --yes)" /dev/null 2>&1)"
    assert_contains "--yes skips the prompt on a terminal" "$out" "--yes given"
    assert_contains "--yes still publishes" "$out" "Published v0.1.0"
else
    printf '  \033[33mskip\033[0m script(1) unavailable: terminal prompt not exercised\n'
fi

# --- the real push is atomic ------------------------------------------------
# A target whose default branch is not main cannot have that branch pruned:
# without --atomic, main lands anyway and every re-run fails identically,
# leaving the public repo half-shaped. Atomic means the target is untouched.
ODD="$WORK/odd-default.git"
git init -q --bare -b master "$ODD"
git -C "$SRC" push -q "$ODD" "v0.1.0^{commit}:refs/heads/master"
odd_before="$(git -C "$ODD" for-each-ref --format='%(refname)' | sort | tr '\n' ' ')"
if SOURCE="$SRC" TARGET="$ODD" CLONE_DIR="$WORK/unused" \
    "$REPO_ROOT/scripts/mirror-release.sh" --no-release-page --no-reset-local v0.1.0 \
    >/dev/null 2>&1; then
    odd_pushed=yes
else
    odd_pushed=no
fi
assert_eq "push to a target with an unprunable default branch fails" "$odd_pushed" "no"
assert_eq "the rejected push left the target untouched" \
    "$(git -C "$ODD" for-each-ref --format='%(refname)' | sort | tr '\n' ' ')" "$odd_before"

# --- the local clone is only reset when it really is the target's clone ------
git clone -q "$TGT" "$WORK/clone"
git clone -q "$SRC" "$WORK/wrong-clone"
assert_fails "refuses to reset a clone whose origin is not the target" bash -c \
    "SOURCE='$SRC' TARGET='$TGT' CLONE_DIR='$WORK/wrong-clone' \
     '$REPO_ROOT/scripts/mirror-release.sh' --no-release-page v0.1.0"
assert_eq "the refused run pushed nothing" \
    "$(git -C "$TGT" rev-parse 'refs/heads/main^')" "$V020"

echo "stray" > "$WORK/clone/stray.txt"
git -C "$WORK/clone" add stray.txt
out="$(SOURCE="$SRC" TARGET="$TGT" CLONE_DIR="$WORK/clone" \
    "$REPO_ROOT/scripts/mirror-release.sh" --no-release-page v0.1.0 2>&1)"
assert_contains "warns that local changes in the clone will be discarded" "$out" \
    "will discard them"
assert_eq "the local clone is reset to the published state" \
    "$(git -C "$WORK/clone" rev-parse HEAD)" "$(git -C "$TGT" rev-parse refs/heads/main)"
assert_empty "the reset discarded the stray change" \
    "$(git -C "$WORK/clone" status --porcelain)"

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
