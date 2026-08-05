#!/usr/bin/env bash
#
# Offline test for scripts/release.sh. Builds a fixture repo with a local bare
# origin, copies scripts/ into it, and drives release.sh there. Never touches
# a network remote and never calls gh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=scripts/tests/assert.sh
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

# `--` must not silently swallow the version: it used to leave VERSION empty,
# which printed usage here but published the wrong release in mirror-release.sh.
out="$(run_release -- 0.1.0 || true)"
assert_contains "rejects the -- option terminator" "$out" "unknown option: --"
assert_empty "-- run creates no tag" "$(git -C "$FIXTURE" tag -l)"

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

# --- signing: the one mandatory project guarantee ---------------------------
#
# `cat-file -t` reports "tag" for signed and unsigned annotated tags alike, so
# it cannot catch a dropped -S/-s. Look at the objects themselves.
if git -C "$FIXTURE" cat-file commit HEAD | grep -q '^gpgsig'; then
    commit_signed=yes
else
    commit_signed=no
fi
assert_eq "release commit carries a signature header" "$commit_signed" "yes"

if git -C "$FIXTURE" cat-file commit HEAD | grep -q '^Signed-off-by: '; then
    commit_signoff=yes
else
    commit_signoff=no
fi
assert_eq "release commit carries a Signed-off-by trailer" "$commit_signoff" "yes"

if git -C "$FIXTURE" cat-file tag v0.1.0 | grep -q 'BEGIN SSH SIGNATURE'; then
    tag_signed=yes
else
    tag_signed=no
fi
assert_eq "release tag is cryptographically signed" "$tag_signed" "yes"

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

# --- third release: no non-merge conventional commits since the previous tag
# (the "No changes recorded." fallback path) must still leave a blank line
# separating the new section from the prior "## v" header.
run_release 0.3.0 >/dev/null
assert_contains "third release tags despite no new commits" \
    "$(git -C "$FIXTURE" tag -l)" "v0.3.0"
changelog="$(cat "$FIXTURE/CHANGELOG.md")"
assert_contains "changelog records no changes for the empty range" \
    "$changelog" "No changes recorded."
line_before_prior_header="$(awk '/^## v0\.2\.0/{print prev; exit} {prev=$0}' "$FIXTURE/CHANGELOG.md")"
assert_empty "blank line separates the no-changes section from the prior header" \
    "$line_before_prior_header"

# --- a pre-release tag is not a release ------------------------------------
# The shared definition in scripts/lib/release-tag.sh must not treat v0.4.0-rc1
# as the previous release; the notes range has to stay anchored at v0.3.0.
git -C "$FIXTURE" tag -a v0.4.0-rc1 -m "prerelease"
out="$(run_release --dry-run 0.4.0)"
assert_contains "pre-release tag is not the previous release" "$out" "Commit range : v0.3.0..HEAD"
assert_eq "remote URL is printed alongside the remote name" \
    "$(printf '%s\n' "$out" | grep -c "Remote *: origin ($ORIGIN)")" "1"

# --- a failed commit restores the worktree ---------------------------------
# Signing is mandatory, so point user.signingkey at a file that does not exist:
# the bump and the CHANGELOG rewrite have already happened when the commit
# fails. The rollback trap must undo them, because "commit the leftovers" would
# land a version bump with no tag and poison 0.4.0 forever.
head_before="$(git -C "$FIXTURE" rev-parse HEAD)"
git -C "$FIXTURE" config user.signingkey "$WORK/no-such-key.pub"
if run_release 0.4.0 >/dev/null 2>&1; then
    commit_failed=no
else
    commit_failed=yes
fi
assert_eq "release fails when the commit cannot be signed" "$commit_failed" "yes"
assert_empty "failed commit leaves no uncommitted changes" \
    "$(git -C "$FIXTURE" status --porcelain --untracked-files=no)"
assert_eq "failed commit leaves HEAD where it was" \
    "$(git -C "$FIXTURE" rev-parse HEAD)" "$head_before"
assert_eq "failed commit leaves pyproject.toml unbumped" \
    "$(sed -n 's/^version = "\(.*\)"$/\1/p' "$FIXTURE/pyproject.toml" | head -1)" "0.3.0"
case "$(cat "$FIXTURE/CHANGELOG.md")" in
    *"## v0.4.0"*) leftover_section=yes ;;
    *)             leftover_section=no ;;
esac
assert_eq "failed commit leaves no half-written CHANGELOG section" "$leftover_section" "no"
assert_empty "failed commit creates no tag for that version" \
    "$(git -C "$FIXTURE" tag -l v0.4.0)"

git -C "$FIXTURE" config user.signingkey "$WORK/signing-key.pub"
run_release 0.4.0 >/dev/null
assert_eq "re-run after a failed commit succeeds" \
    "$(git -C "$FIXTURE" tag -l v0.4.0)" "v0.4.0"

# --- a failed push is resumable -------------------------------------------
# A rejecting pre-receive hook on the bare origin gives the real-world state:
# the signed commit and tag exist locally, nothing reached the remote.
cat > "$ORIGIN/hooks/pre-receive" <<'EOF'
#!/bin/sh
echo "rejected by test hook" >&2
exit 1
EOF
chmod +x "$ORIGIN/hooks/pre-receive"

if run_release 0.5.0 >/dev/null 2>&1; then
    push_failed=no
else
    push_failed=yes
fi
assert_eq "release fails when the push is rejected" "$push_failed" "yes"
assert_eq "failed push keeps the local tag" "$(git -C "$FIXTURE" tag -l v0.5.0)" "v0.5.0"
assert_eq "failed push keeps the local release commit" \
    "$(git -C "$FIXTURE" log -1 --format=%s)" "chore(release): v0.5.0"
assert_empty "failed push leaves the worktree clean" \
    "$(git -C "$FIXTURE" status --porcelain --untracked-files=no)"
assert_empty "failed push published no tag" "$(git -C "$ORIGIN" tag -l v0.5.0)"

rm -f "$ORIGIN/hooks/pre-receive"
out="$(run_release 0.5.0)"
assert_contains "re-run after a failed push resumes at the push" "$out" "Resuming at the push"
assert_eq "re-run after a failed push publishes the tag" \
    "$(git -C "$ORIGIN" tag -l v0.5.0)" "v0.5.0"
assert_eq "re-run after a failed push publishes the commit" \
    "$(git -C "$ORIGIN" rev-parse main)" "$(git -C "$FIXTURE" rev-parse HEAD)"
assert_eq "re-run after a failed push does not re-tag" \
    "$(git -C "$FIXTURE" tag -l | grep -c '^v0.5.0$')" "1"

# --- a hand-written CHANGELOG preamble survives ---------------------------
# First line is something other than "# Changelog", which used to be discarded
# unconditionally by `tail -n +2`.
{
    printf 'Hand-written preamble line\n\n'
    tail -n +2 "$FIXTURE/CHANGELOG.md"
} > "$WORK/changelog-with-preamble"
cp "$WORK/changelog-with-preamble" "$FIXTURE/CHANGELOG.md"
git -C "$FIXTURE" add CHANGELOG.md
git -C "$FIXTURE" commit -q -m "docs: add a changelog preamble"
git -C "$FIXTURE" push -q origin main

run_release 0.6.0 >/dev/null
changelog="$(cat "$FIXTURE/CHANGELOG.md")"
assert_contains "hand-written first line is preserved" "$changelog" "Hand-written preamble line"
assert_eq "changelog still starts with the header" \
    "$(head -1 "$FIXTURE/CHANGELOG.md")" "# Changelog"
assert_eq "the header is not duplicated" \
    "$(grep -c '^# Changelog$' "$FIXTURE/CHANGELOG.md")" "1"

assert_summary
