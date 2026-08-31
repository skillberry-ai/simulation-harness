#!/usr/bin/env bash
#
# Offline test for scripts/check-dco.sh. Builds throwaway git repos with known
# sign-off states and asserts the pass/fail verdict. Touches no network remote.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/assert.sh
source "$SCRIPT_DIR/assert.sh"

CHECK="$SCRIPT_DIR/../check-dco.sh"

TMPDIR_TEST="$(mktemp -d "${TMPDIR:-/tmp}/test-check-dco.XXXXXX")"
trap 'rm -rf -- "$TMPDIR_TEST"' EXIT

AUTHOR_NAME="Test Author"
AUTHOR_EMAIL="test@example.com"

fixture_repo() {
    local dir="$1"
    git init -q -b main "$dir"
    git -C "$dir" config user.email "$AUTHOR_EMAIL"
    git -C "$dir" config user.name "$AUTHOR_NAME"
    git -C "$dir" config commit.gpgsign false
    git -C "$dir" config tag.gpgsign false
    # Base commit, always signed off, so ranges have somewhere to start.
    echo base > "$dir/file.txt"
    git -C "$dir" add file.txt
    git -C "$dir" commit -q -m "chore: base" -m "Signed-off-by: $AUTHOR_NAME <$AUTHOR_EMAIL>"
}

# commit <dir> <subject> [trailer-line] [filename]
# Defaults to file.txt; pass a distinct filename for commits on diverging
# branches, so a later merge does not conflict on shared content.
commit() {
    local dir="$1" subject="$2" trailer="${3:-}" file="${4:-file.txt}"
    echo "$subject" >> "$dir/$file"
    git -C "$dir" add "$file"
    if [[ -n "$trailer" ]]; then
        git -C "$dir" commit -q -m "$subject" -m "$trailer"
    else
        git -C "$dir" commit -q -m "$subject"
    fi
}

run_check() {
    local dir="$1" base="$2" head="$3"
    ( cd "$dir" && "$CHECK" "$base" "$head" 2>&1 )
}

echo "== a properly signed-off commit passes"
R="$TMPDIR_TEST/signed"; fixture_repo "$R"
commit "$R" "feat: signed" "Signed-off-by: $AUTHOR_NAME <$AUTHOR_EMAIL>"
out="$(run_check "$R" main~1 main || true)"
assert_contains "reports ok" "$out" "DCO ok"
( cd "$R" && "$CHECK" main~1 main >/dev/null 2>&1 )
assert_eq "exits zero" "$?" "0"

echo "== a commit with no trailer fails, and says so"
R="$TMPDIR_TEST/unsigned"; fixture_repo "$R"
commit "$R" "feat: unsigned"
assert_fails "exits non-zero" bash -c "cd '$R' && '$CHECK' main~1 main"
out="$(run_check "$R" main~1 main || true)"
assert_contains "names the missing trailer" "$out" "no Signed-off-by trailer"
assert_contains "names the offending subject" "$out" "feat: unsigned"
assert_contains "tells the contributor how to fix it" "$out" "git rebase --signoff"

echo "== a trailer naming someone else fails as a mismatch, not as missing"
R="$TMPDIR_TEST/mismatch"; fixture_repo "$R"
commit "$R" "feat: wrong signer" "Signed-off-by: Someone Else <other@example.com>"
assert_fails "exits non-zero" bash -c "cd '$R' && '$CHECK' main~1 main"
out="$(run_check "$R" main~1 main || true)"
assert_contains "distinguishes mismatch from absence" "$out" "does not match the author"

echo "== case and surrounding whitespace do not matter"
R="$TMPDIR_TEST/case"; fixture_repo "$R"
commit "$R" "feat: odd case" "Signed-off-by:   test author <TEST@Example.com>  "
out="$(run_check "$R" main~1 main || true)"
assert_contains "normalizes case and spacing" "$out" "DCO ok"

echo "== merge commits are exempt"
R="$TMPDIR_TEST/merge"; fixture_repo "$R"
git -C "$R" checkout -q -b side
commit "$R" "feat: side work" "Signed-off-by: $AUTHOR_NAME <$AUTHOR_EMAIL>" side.txt
git -C "$R" checkout -q main
commit "$R" "feat: main work" "Signed-off-by: $AUTHOR_NAME <$AUTHOR_EMAIL>" main.txt
# --no-ff forces a merge commit, which git creates without a sign-off trailer.
git -C "$R" merge -q --no-ff --no-edit side
out="$(run_check "$R" main~2 main || true)"
assert_contains "skips the unsigned merge commit" "$out" "DCO ok"

echo "== bot commits are exempt"
R="$TMPDIR_TEST/bot"; fixture_repo "$R"
echo bot >> "$R/file.txt"
git -C "$R" add file.txt
GIT_AUTHOR_NAME="dependabot[bot]" \
GIT_AUTHOR_EMAIL="49699333+dependabot[bot]@users.noreply.github.com" \
    git -C "$R" commit -q -m "chore(deps): bump something"
out="$(run_check "$R" main~1 main || true)"
assert_contains "exempts the bot commit" "$out" "bot commit(s) exempt"

echo "== an empty range passes"
R="$TMPDIR_TEST/empty"; fixture_repo "$R"
out="$(run_check "$R" main main || true)"
assert_contains "no commits is not a failure" "$out" "DCO ok"

echo "== only the branch's own commits are checked when base has advanced"
R="$TMPDIR_TEST/moved"; fixture_repo "$R"
git -C "$R" checkout -q -b feature
commit "$R" "feat: branch work" "Signed-off-by: $AUTHOR_NAME <$AUTHOR_EMAIL>" feature.txt
git -C "$R" checkout -q main
# An unsigned commit lands on the base branch after the feature branch was cut.
commit "$R" "feat: unrelated unsigned commit on base" "" base-side.txt
out="$(run_check "$R" main feature || true)"
assert_contains "base-branch commits are excluded via merge-base" "$out" "DCO ok"

echo "== a bad invocation is rejected"
assert_fails "missing arguments exit non-zero" bash -c "cd '$R' && '$CHECK' main"
assert_fails "an unresolvable ref exits non-zero" bash -c "cd '$R' && '$CHECK' main nope-not-a-ref"

assert_summary
