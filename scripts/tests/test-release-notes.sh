#!/usr/bin/env bash
#
# Offline test for scripts/lib/release-notes.sh. Builds a throwaway git repo
# with known Conventional Commit subjects and asserts the generated markdown.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/tests/assert.sh
source "$SCRIPT_DIR/assert.sh"
# shellcheck source=scripts/lib/release-notes.sh
source "$SCRIPT_DIR/../lib/release-notes.sh"

TMPDIR_TEST="$(mktemp -d "${TMPDIR:-/tmp}/test-release-notes.XXXXXX")"
trap 'rm -rf -- "$TMPDIR_TEST"' EXIT

fixture_repo() {
    local dir="$1"
    git init -q -b main "$dir"
    git -C "$dir" config user.email "test@example.com"
    git -C "$dir" config user.name "Test"
    git -C "$dir" config commit.gpgsign false
    git -C "$dir" config tag.gpgsign false
}

commit() {
    git -C "$TMPDIR_TEST/repo" commit -q --allow-empty -m "$1"
}

# commit_with_body <subject> <body> — for footer-form breaking changes, which
# live in the body rather than the subject.
commit_with_body() {
    git -C "$TMPDIR_TEST/repo" commit -q --allow-empty -m "$1" -m "$2"
}

echo "test-release-notes.sh"

fixture_repo "$TMPDIR_TEST/repo"
commit "feat(api): add endpoint"
commit "fix: correct off-by-one"
commit "chore(deps): bump thing"
commit "not a conventional subject"
commit "feat!: breaking change"
commit "docs(readme): tidy wording"

expected="$(cat <<'EOF'
### Breaking changes

- breaking change

### Features

- **api:** add endpoint
- breaking change

### Fixes

- correct off-by-one

### Documentation

- **readme:** tidy wording

### Chores

- **deps:** bump thing

### Other

- not a conventional subject
EOF
)"

actual="$(cd "$TMPDIR_TEST/repo" && generate_release_notes HEAD)"
assert_eq "groups by type in declared order, scopes bolded" "$actual" "$expected"

empty="$(cd "$TMPDIR_TEST/repo" && generate_release_notes 'HEAD..HEAD')"
assert_empty "empty range produces no output" "$empty"

assert_eq "unknown type falls back to Other" "$(release_notes_heading zzz)" "Other"
assert_eq "feat maps to Features" "$(release_notes_heading feat)" "Features"

# A range starting at a tag excludes the tagged commit itself.
git -C "$TMPDIR_TEST/repo" tag -a v0.1.0 -m "Release v0.1.0"
commit "fix(state): repair store reload"
since_tag="$(cd "$TMPDIR_TEST/repo" && generate_release_notes 'v0.1.0..HEAD')"
assert_eq "range since tag lists only newer commits" "$since_tag" "$(cat <<'EOF'
### Fixes

- **state:** repair store reload
EOF
)"

# A real merge commit: its own "Merge branch ..." subject must be excluded
# from the notes (--no-merges), while the commit it brings in is still
# listed. This exercises merge-commit exclusion, which the linear fixture
# above never touches.
git -C "$TMPDIR_TEST/repo" tag -a v0.2.0 -m "Release v0.2.0"
git -C "$TMPDIR_TEST/repo" checkout -q -b feature-branch
commit "feat(widgets): add widget"
git -C "$TMPDIR_TEST/repo" checkout -q main
git -C "$TMPDIR_TEST/repo" merge -q --no-ff -m "Merge branch 'feature-branch'" feature-branch

since_merge="$(cd "$TMPDIR_TEST/repo" && generate_release_notes 'v0.2.0..HEAD')"
assert_contains "merge range includes the merged branch's own commit" "$since_merge" "add widget"

case "$since_merge" in
    *"Merge branch"*) merge_subject_present="yes" ;;
    *)                 merge_subject_present="no" ;;
esac
assert_eq "merge range excludes the merge commit's own subject" "$merge_subject_present" "no"

# --- Breaking changes -------------------------------------------------------
# Two declaration forms have to work: `!` in the subject (covered above) and a
# BREAKING CHANGE footer in the body, which is the form release commits in this
# repo actually use.

BREAK="$TMPDIR_TEST/breaking"
fixture_repo "$BREAK"
# fixture_repo/commit target $TMPDIR_TEST/repo, so drive this repo directly.
git -C "$BREAK" commit -q --allow-empty -m "refactor(config): drop dead knob" \
    -m "BREAKING CHANGE: a harness.yaml still setting llm.foo now fails
validation at startup. Delete the line." \
    -m "Signed-off-by: Test Author <test@example.com>"
out="$(cd "$BREAK" && generate_release_notes HEAD)"

assert_contains "footer form produces a Breaking changes section" "$out" "### Breaking changes"
assert_contains "footer prose is used, not the subject" "$out" \
    "**config:** a harness.yaml still setting llm.foo now fails validation at startup. Delete the line."
assert_contains "the commit still appears under its own type" "$out" "- **config:** drop dead knob"
case "$out" in
    "### Breaking changes"*) _assert_pass "Breaking changes leads the notes" ;;
    *) _assert_fail "Breaking changes leads the notes" "notes began: ${out%%$'\n'*}" ;;
esac
case "$out" in
    *Signed-off-by*) _assert_fail "trailers are excluded from the footer" "found Signed-off-by in notes" ;;
    *) _assert_pass "trailers are excluded from the footer" ;;
esac

NOBREAK="$TMPDIR_TEST/nobreaking"
fixture_repo "$NOBREAK"
git -C "$NOBREAK" commit -q --allow-empty -m "fix(api): ordinary fix"
plain="$(cd "$NOBREAK" && generate_release_notes HEAD)"
case "$plain" in
    *"Breaking changes"*) _assert_fail "no section when nothing is breaking" "unexpected section" ;;
    *) _assert_pass "no section when nothing is breaking" ;;
esac

assert_eq "breaking maps to Breaking changes" "$(release_notes_heading breaking)" "Breaking changes"

assert_summary
