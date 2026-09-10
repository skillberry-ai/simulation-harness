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
assert_contains "commits already on the base branch are excluded" "$out" "DCO ok"

# Regression: the range used to be MERGE_BASE..HEAD. With a single merge base
# that is identical to BASE..HEAD, but a criss-cross history has two, and
# `git merge-base` returns only one of them -- so commits reachable from the
# other were dragged into the range even though the base branch already carries
# them. Here F1 is unsigned and already merged into main; only a BASE..HEAD
# range leaves it out.
echo "== a criss-cross history does not drag in commits the base already has"
R="$TMPDIR_TEST/crisscross"; fixture_repo "$R"
git -C "$R" checkout -q -b feature
commit "$R" "feat: unsigned, later merged into base" "" feature.txt
F1="$(git -C "$R" rev-parse HEAD)"
git -C "$R" checkout -q main
commit "$R" "feat: base work" "Signed-off-by: $AUTHOR_NAME <$AUTHOR_EMAIL>" main.txt
# Each branch merges a commit of the other's, leaving two merge bases.
git -C "$R" checkout -q feature
git -C "$R" merge -q --no-ff --no-edit main
git -C "$R" checkout -q main
git -C "$R" merge -q --no-ff --no-edit "$F1"
assert_eq "the fixture really has two merge bases" \
    "$(git -C "$R" merge-base --all main feature | wc -l | tr -d ' ')" "2"
out="$(run_check "$R" main feature || true)"
assert_contains "the base branch's own unsigned commit is not reported" "$out" "DCO ok"

echo "== a bad invocation is rejected"
assert_exit_code "missing arguments exit 2" 2 bash -c "cd '$R' && '$CHECK' main"
assert_exit_code "an unresolvable head ref exits 2" 2 \
    bash -c "cd '$R' && '$CHECK' main nope-not-a-ref"
assert_exit_code "an unresolvable base ref exits 2" 2 \
    bash -c "cd '$R' && '$CHECK' nope-not-a-ref main"

assert_summary
