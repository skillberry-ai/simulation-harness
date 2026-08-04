#!/usr/bin/env bash
#
# Offline test for scripts/release.sh. Builds a fixture repo with a local bare
# origin, copies scripts/ into it, and drives release.sh there. Never touches
# a network remote and never calls gh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck disable=SC1091 source=scripts/tests/assert.sh
source "$SCRIPT_DIR/assert.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/test-release.XXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT

FIXTURE="$WORK/repo"
ORIGIN="$WORK/origin.git"

echo "test-release.sh"

# --- fixture: a repo with pyproject.toml, scripts/, and a local bare origin ---
#
# release.sh passes -S and -s unconditionally, which forces signing regardless of
# commit.gpgsign. Give the fixture its own throwaway SSH signing key so the test
# never depends on the developer's real key or on an ssh-agent being unlocked.
ssh-keygen -q -t ed25519 -N "" -C "release-test" -f "$WORK/signing-key"

git init -q --bare -b main "$ORIGIN"
git init -q -b main "$FIXTURE"
git -C "$FIXTURE" config user.email "test@example.com"
git -C "$FIXTURE" config user.name "Test"
git -C "$FIXTURE" config gpg.format ssh
git -C "$FIXTURE" config user.signingkey "$WORK/signing-key.pub"
git -C "$FIXTURE" config commit.gpgsign false
git -C "$FIXTURE" config tag.gpgsign false
git -C "$FIXTURE" remote add origin "$ORIGIN"

mkdir -p "$FIXTURE/scripts"
cp -r "$REPO_ROOT/scripts/lib" "$FIXTURE/scripts/"
cp "$REPO_ROOT/scripts/release.sh" "$FIXTURE/scripts/"
cat > "$FIXTURE/pyproject.toml" <<'EOF'
[project]
name = "fixture"
version = "0.1.0"
EOF

git -C "$FIXTURE" add -A
git -C "$FIXTURE" commit -q -m "chore: initial fixture"
git -C "$FIXTURE" commit -q --allow-empty -m "feat(api): add an endpoint"
git -C "$FIXTURE" commit -q --allow-empty -m "fix: repair a thing"
git -C "$FIXTURE" push -q origin main

run_release() {
    ( cd "$FIXTURE" && RELEASE_SKIP_GH=1 ./scripts/release.sh "$@" 2>&1 )
}

# --- dry run: reports, changes nothing -------------------------------------
out="$(run_release --dry-run 0.1.0)"
assert_contains "dry run names the tag" "$out" "v0.1.0"
assert_contains "dry run includes generated notes" "$out" "**api:** add an endpoint"
assert_contains "dry run says nothing was written" "$out" "dry run"
assert_empty "dry run leaves the worktree clean" \
    "$(git -C "$FIXTURE" status --porcelain --untracked-files=no)"
assert_empty "dry run creates no tag" "$(git -C "$FIXTURE" tag -l)"

# --- preflight rejections ---------------------------------------------------
assert_fails "rejects a non-semver version" bash -c \
    "cd '$FIXTURE' && RELEASE_SKIP_GH=1 ./scripts/release.sh 1.2"
assert_fails "rejects a missing version" bash -c \
    "cd '$FIXTURE' && RELEASE_SKIP_GH=1 ./scripts/release.sh"

git -C "$FIXTURE" checkout -q -b side
assert_fails "rejects running off main" bash -c \
    "cd '$FIXTURE' && RELEASE_SKIP_GH=1 ./scripts/release.sh 0.1.0"
git -C "$FIXTURE" checkout -q main

echo "dirty" >> "$FIXTURE/pyproject.toml"
assert_fails "rejects a dirty worktree" bash -c \
    "cd '$FIXTURE' && RELEASE_SKIP_GH=1 ./scripts/release.sh 0.1.0"
git -C "$FIXTURE" checkout -q -- pyproject.toml

git -C "$FIXTURE" commit -q --allow-empty -m "chore: unpushed work"
assert_fails "rejects main ahead of origin" bash -c \
    "cd '$FIXTURE' && RELEASE_SKIP_GH=1 ./scripts/release.sh 0.1.0"
git -C "$FIXTURE" reset -q --hard origin/main

# --- first release: version equal to pyproject is allowed -------------------
run_release 0.1.0 >/dev/null
assert_eq "creates the tag" "$(git -C "$FIXTURE" tag -l)" "v0.1.0"
assert_eq "tag is annotated" \
    "$(git -C "$FIXTURE" cat-file -t "$(git -C "$FIXTURE" rev-parse v0.1.0)")" "tag"
assert_eq "release commit subject" \
    "$(git -C "$FIXTURE" log -1 --format=%s)" "chore(release): v0.1.0"
assert_eq "pyproject version unchanged at 0.1.0" \
    "$(sed -n 's/^version = "\(.*\)"$/\1/p' "$FIXTURE/pyproject.toml" | head -1)" "0.1.0"
assert_contains "changelog has the section" \
    "$(cat "$FIXTURE/CHANGELOG.md")" "## v0.1.0"
assert_contains "changelog lists the feat" \
    "$(cat "$FIXTURE/CHANGELOG.md")" "**api:** add an endpoint"
assert_eq "changelog starts with the header" \
    "$(head -1 "$FIXTURE/CHANGELOG.md")" "# Changelog"
assert_eq "pushed the tag to origin" \
    "$(git -C "$ORIGIN" tag -l)" "v0.1.0"

# --- second release: equal version now rejected, bump required -------------
git -C "$FIXTURE" commit -q --allow-empty -m "fix(state): repair reload"
git -C "$FIXTURE" push -q origin main
assert_fails "rejects a non-increasing version once tagged" bash -c \
    "cd '$FIXTURE' && RELEASE_SKIP_GH=1 ./scripts/release.sh 0.1.0"
assert_fails "rejects a lower version" bash -c \
    "cd '$FIXTURE' && RELEASE_SKIP_GH=1 ./scripts/release.sh 0.0.9"

run_release 0.2.0 >/dev/null
assert_eq "pyproject bumped" \
    "$(sed -n 's/^version = "\(.*\)"$/\1/p' "$FIXTURE/pyproject.toml" | head -1)" "0.2.0"
changelog="$(cat "$FIXTURE/CHANGELOG.md")"
assert_contains "newest section listed first" \
    "$(printf '%s\n' "$changelog" | grep -m1 '^## ')" "v0.2.0"
assert_contains "second release notes scoped to new commits" "$changelog" "**state:** repair reload"
assert_eq "both tags present on origin" \
    "$(git -C "$ORIGIN" tag -l | sort -V | tr '\n' ' ')" "v0.1.0 v0.2.0 "

assert_summary
