#!/usr/bin/env bash
#
# release.sh — cut a numbered release of this repo.
#
# Bumps the version in pyproject.toml, prepends a CHANGELOG.md section built
# from Conventional Commit subjects since the last release, commits and signs
# an annotated tag, pushes, and creates the GitHub Release on the internal repo.
#
# This does NOT build a container image. GitHub Actions is unavailable on
# github.ibm.com, so docker-publish.yml never runs here despite its v*.*.* tag
# trigger. The image is built on the mirror when the release is published there
# by scripts/mirror-release.sh — see docs/releasing.md, "Container images".
#
# Usage:
#   scripts/release.sh [--dry-run] <X.Y.Z>
#
set -euo pipefail

PROG="${0##*/}"

err()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

usage() {
    cat >&2 <<EOF
Usage: $PROG [--dry-run] <X.Y.Z>

Cut release vX.Y.Z of this repo: bump pyproject.toml, write CHANGELOG.md,
commit, create a signed annotated tag, push, and create the GitHub Release.

Options:
  --dry-run   Print the generated notes and every planned action; write nothing.
  -h, --help  Show this help and exit.

Environment overrides (used by scripts/tests/test-release.sh):
  RELEASE_REMOTE    git remote to push to (default: origin)
  RELEASE_GH_REPO   HOST/OWNER/REPO for gh (default: github.ibm.com/kaegis/simulation-harness)
  RELEASE_SKIP_GH   set to 1 to skip the gh release create call
EOF
    exit "${1:-2}"
}

DRY_RUN=0
VERSION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage 0 ;;
        # No `--` case on purpose: the only positional is a version, which can
        # never look like an option, and a `--` that failed to drain "$@" into
        # VERSION would silently release something other than what was asked
        # for. `--` therefore falls through to the unknown-option die below.
        -*)        die "unknown option: $1" ;;
        *)         [[ -z "$VERSION" ]] || die "unexpected extra argument: $1"
                   VERSION="$1"; shift ;;
    esac
done

[[ -n "$VERSION" ]] || usage 2
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must be X.Y.Z (got '$VERSION')"

TAG="v$VERSION"

REPO_ROOT="$(git rev-parse --show-toplevel)" || die "not inside a git repository"
cd "$REPO_ROOT"

# shellcheck source=scripts/lib/release-notes.sh
source "$REPO_ROOT/scripts/lib/release-notes.sh"
# shellcheck source=scripts/lib/release-tag.sh
source "$REPO_ROOT/scripts/lib/release-tag.sh"

: "${RELEASE_REMOTE:=origin}"
: "${RELEASE_GH_REPO:=github.ibm.com/kaegis/simulation-harness}"
: "${RELEASE_SKIP_GH:=0}"

# ROLLBACK_TO is armed with the pre-mutation HEAD just before the worktree is
# touched and disarmed once the tag exists. While armed, any exit — a failed
# signed commit, a failed tag — restores the worktree to exactly what preflight
# found, which it proved clean. Without it a failed commit leaves a bumped
# pyproject.toml and a written CHANGELOG.md staged, and the obvious next move
# (committing them) permanently poisons that version number.
#
# Declared, along with every tempfile the script owns, before the first one is
# created, so the trap can be installed before anything exists to leak.
ROLLBACK_TO=""
NOTES_FILE=""
SECTION_FILE=""
on_exit() {
    if [[ -n "$ROLLBACK_TO" ]]; then
        warn "release aborted part-way — restoring the worktree to $ROLLBACK_TO"
        rm -f -- pyproject.toml.new CHANGELOG.md.new
        git reset --hard --quiet "$ROLLBACK_TO" \
            || warn "could not restore the worktree; inspect 'git status' before retrying"
    fi
    local f
    for f in "$NOTES_FILE" "$SECTION_FILE"; do
        if [[ -n "$f" ]]; then
            rm -f -- "$f"
        fi
    done
}
trap on_exit EXIT

NOTES_FILE="$(mktemp "${TMPDIR:-/tmp}/release-notes.XXXXXX")"

# ---- helpers ---------------------------------------------------------------

# Current version from the first `version = "..."` line in pyproject.toml.
current_version() {
    sed -n 's/^version = "\([^"]*\)"$/\1/p' pyproject.toml | head -1
}

# version_gt <a> <b> — true when a sorts strictly after b.
version_gt() {
    [[ "$1" != "$2" ]] || return 1
    [[ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1)" == "$1" ]]
}

# Extract the CHANGELOG.md section for a version, used when resuming.
changelog_section() {
    awk -v want="## $TAG " '
        index($0, want) == 1 { grab = 1; next }
        grab && /^## / { exit }
        grab { print }
    ' CHANGELOG.md | sed '/./,$!d'
}

push_release() {
    info "Pushing main and $TAG to $RELEASE_REMOTE"
    # --atomic: main and the tag are one release, so they must land together or
    # not at all. Non-atomically, a rule that rejects only the branch leaves the
    # tag published with no release commit on main — and the next run then sees
    # the pushed tag, resumes at the GitHub release step, and reports success
    # with the remote still behind. Atomic routes that failure to the
    # resume-at-push arm instead.
    git push --atomic "$RELEASE_REMOTE" main "$TAG" \
        || die "push failed; nothing was published (the push is atomic) and the local commit and tag are intact — fix the cause and re-run 'scripts/release.sh $VERSION', which resumes at the push"
}

# True only when HEAD is a release commit this script produced for $TAG. A tag
# that merely happens to sit at HEAD — created by hand, or by something else —
# must not trigger a resume: there would be no version bump and no CHANGELOG
# section to publish, and the run would report success having done neither.
#
# The subject below must stay in step with the `git commit -m` in the mutation
# phase; it is matched literally, so rewording one without the other silently
# disables resuming on both arms.
head_is_release_commit() {
    [[ -f pyproject.toml ]] || return 1
    [[ "$(git log -1 --format=%s)" == "chore(release): $TAG" ]] || return 1
    [[ "$(current_version)" == "$VERSION" ]]
}

# Fill NOTES_FILE from the already-written CHANGELOG.md section, used on both
# resume paths where the notes were generated by the earlier run.
resume_notes() {
    if [[ -f CHANGELOG.md ]]; then
        changelog_section > "$NOTES_FILE"
    fi
    if [[ ! -s "$NOTES_FILE" ]]; then
        printf 'See CHANGELOG.md.\n' > "$NOTES_FILE"
    fi
}

create_gh_release() {
    if [[ "$RELEASE_SKIP_GH" == "1" ]]; then
        info "RELEASE_SKIP_GH=1 — skipping the GitHub release."
        return 0
    fi
    command -v gh >/dev/null 2>&1 || die "gh is not installed or not on PATH"
    if gh release view "$TAG" -R "$RELEASE_GH_REPO" >/dev/null 2>&1; then
        info "GitHub release $TAG already exists on $RELEASE_GH_REPO — leaving it alone."
        return 0
    fi
    info "Creating the GitHub release on $RELEASE_GH_REPO"
    gh release create "$TAG" -R "$RELEASE_GH_REPO" \
        --title "$TAG" --notes-file "$NOTES_FILE" \
        || die "gh release create failed; re-run this script to retry"
}

# ---- resume detection ------------------------------------------------------

info "Fetching $RELEASE_REMOTE"
git fetch --quiet --tags "$RELEASE_REMOTE" || die "failed to fetch $RELEASE_REMOTE"

# Ask for the peeled ref too ("refs/tags/<tag>^{}"), which is the commit an
# annotated tag points at on the remote. Resolving the *remote* tag's commit
# matters: using the local tag's commit would only prove the remote has some tag
# with that name, and `git fetch --tags` will not force-update a local tag that
# has diverged from it — so a diverged local tag would resume at the GitHub
# release step and never push main.
ls_remote_out="$(git ls-remote --tags "$RELEASE_REMOTE" "refs/tags/$TAG" "refs/tags/$TAG^{}")" \
    || die "failed to query tags on $RELEASE_REMOTE"
local_tag_commit="$(git rev-parse --verify --quiet "refs/tags/$TAG^{commit}" || true)"
head_commit="$(git rev-parse HEAD)"

remote_tag_commit=""
if [[ -n "$ls_remote_out" ]]; then
    # Prefer the peeled commit; fall back to the ref's own object id, which is
    # the commit when the remote tag is lightweight.
    remote_tag_commit="$(
        awk -v peeled="refs/tags/$TAG^{}" -v plain="refs/tags/$TAG" '
            $2 == peeled { print $1; found = 1; exit }
            $2 == plain  { plain_sha = $1 }
            END { if (!found && plain_sha != "") print plain_sha }
        ' <<< "$ls_remote_out"
    )"
fi

# Both arms are gated on head_is_release_commit: a tag that merely sits at HEAD
# is not evidence of a previous run of this script. A hand-pushed vX.Y.Z would
# otherwise resume straight to the GitHub release step and report success with
# no version bump and no CHANGELOG section behind it.
if [[ -n "$remote_tag_commit" && "$remote_tag_commit" == "$head_commit" ]] \
    && head_is_release_commit; then
    warn "$TAG already exists on $RELEASE_REMOTE and HEAD is unchanged since — a previous run got this far."
    warn "Resuming at the GitHub release step; nothing will be committed or pushed."
    resume_notes
    if (( DRY_RUN )); then
        info "dry run: would create the GitHub release for $TAG with:"
        sed 's/^/    /' "$NOTES_FILE"
        exit 0
    fi
    create_gh_release
    info "Done."
    exit 0
fi

# The tag exists locally at HEAD but never reached the remote: a previous run
# committed and tagged, then failed at the push. Resume at the push. Without
# this arm the run below would die in preflight on "local main differs from
# $RELEASE_REMOTE/main", so the push could never be retried — and the advice to
# pull would put a merge commit on top of the release commit.
if [[ -z "$ls_remote_out" && -n "$local_tag_commit" && "$local_tag_commit" == "$head_commit" ]] \
    && head_is_release_commit; then
    warn "$TAG exists locally at HEAD but not on $RELEASE_REMOTE — a previous run committed and tagged, then failed to push."
    warn "Resuming at the push; nothing will be committed or re-tagged."

    branch="$(git rev-parse --abbrev-ref HEAD)"
    [[ "$branch" == "main" ]] || die "must be on main to resume a release (currently on '$branch')"
    if ! git diff --quiet || ! git diff --cached --quiet; then
        die "worktree has uncommitted changes to tracked files — commit or stash first"
    fi

    resume_notes
    if (( DRY_RUN )); then
        info "dry run: would run: git push $RELEASE_REMOTE main $TAG"
        info "dry run: then create the GitHub release for $TAG with:"
        sed 's/^/    /' "$NOTES_FILE"
        exit 0
    fi
    push_release
    create_gh_release
    info "Done."
    exit 0
fi

# ---- preflight -------------------------------------------------------------

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "main" ]] || die "must be on main to cut a release (currently on '$branch')"

if ! git diff --quiet || ! git diff --cached --quiet; then
    die "worktree has uncommitted changes to tracked files — commit or stash first"
fi

if [[ -n "$(git status --porcelain --untracked-files=normal | grep '^??' || true)" ]]; then
    warn "untracked files present; they will not be part of the release."
fi

[[ "$(git rev-parse HEAD)" == "$(git rev-parse "$RELEASE_REMOTE/main")" ]] \
    || die "local main differs from $RELEASE_REMOTE/main — push or pull first"

if git rev-parse --verify --quiet "refs/tags/$TAG" >/dev/null; then
    die "tag $TAG already exists locally"
fi

[[ -f pyproject.toml ]] || die "pyproject.toml not found at the repo root"
cur="$(current_version)"
[[ -n "$cur" ]] || die "could not read the current version from pyproject.toml"

# uv.lock pins the project's own version, so it has to be re-locked alongside the
# bump. Check for uv here, in preflight, rather than after the worktree has been
# mutated: a missing uv is a "fix your PATH and re-run" problem, not something to
# discover half-way through a release.
if [[ -f uv.lock ]]; then
    command -v uv >/dev/null 2>&1 \
        || die "uv.lock exists but uv is not on PATH — uv is needed to re-lock the version bump"
fi

# Highest existing release tag, per the definition shared with
# mirror-release.sh (scripts/lib/release-tag.sh), so the two can never disagree
# about which tags are releases. Pre-release tags are not releases.
prev_tag="$(release_tag_latest)"
if [[ -z "$prev_tag" ]]; then
    # First release: the version may match pyproject.toml exactly.
    if [[ "$VERSION" != "$cur" ]] && ! version_gt "$VERSION" "$cur"; then
        die "first release must be $cur or higher (got $VERSION)"
    fi
else
    version_gt "$VERSION" "$cur" || die "$VERSION must be greater than the current version $cur"
fi

# ---- notes -----------------------------------------------------------------

range="${prev_tag:+$prev_tag..}HEAD"
generate_release_notes "$range" > "$NOTES_FILE"
if [[ ! -s "$NOTES_FILE" ]]; then
    printf 'No changes recorded.\n' > "$NOTES_FILE"
fi

echo
info "Release plan"
printf '    Tag          : %s\n' "$TAG"
printf '    Version      : %s -> %s\n' "$cur" "$VERSION"
printf '    Commit range : %s\n' "$range"
printf '    Remote       : %s (%s)\n' "$RELEASE_REMOTE" \
    "$(git remote get-url "$RELEASE_REMOTE" 2>/dev/null || printf '<unresolved>')"
printf '    GitHub repo  : %s\n' "$RELEASE_GH_REPO"
echo
info "Release notes"
sed 's/^/    /' "$NOTES_FILE"
echo

if (( DRY_RUN )); then
    info "dry run: nothing was written. Would bump pyproject.toml,"
    if [[ -f uv.lock ]]; then
        info "re-lock uv.lock, prepend CHANGELOG.md, commit"
    else
        info "prepend CHANGELOG.md, commit"
    fi
    info "'chore(release): $TAG', tag, push to $RELEASE_REMOTE, and"
    info "create the GitHub release."
    exit 0
fi

# ---- bump pyproject.toml ---------------------------------------------------

# Everything from here to the tag is one unit: arm the rollback so a failure
# (most likely a signing failure on the commit) cannot leave a bumped version
# and a written CHANGELOG behind. Safe because preflight proved the tracked
# worktree clean at this commit. Disarmed as soon as the tag exists, so a
# failed *push* keeps the commit and tag for the resume path above.
ROLLBACK_TO="$(git rev-parse HEAD)"

info "Setting version to $VERSION in pyproject.toml"
awk -v v="$VERSION" '
    !done && /^version = "/ { sub(/"[^"]*"/, "\"" v "\""); done = 1 }
    { print }
' pyproject.toml > pyproject.toml.new
mv pyproject.toml.new pyproject.toml

[[ "$(current_version)" == "$VERSION" ]] || die "failed to update the version in pyproject.toml"

# ---- re-lock ---------------------------------------------------------------

# uv.lock carries the project's own version in its [[package]] entry, so the bump
# above leaves it stale. Left unfixed the release ships a lockfile that disagrees
# with pyproject.toml, and the next `uv run` silently rewrites it — the change then
# turns up as an unrelated dirty file in whoever's branch touches it next.
# The rollback trap is armed, so a failure here restores the bump.
if [[ -f uv.lock ]]; then
    info "Re-locking uv.lock for $VERSION"
    uv lock || die "uv lock failed — see the output above. The worktree is restored below."
fi

# ---- prepend the CHANGELOG section ----------------------------------------

info "Prepending the v$VERSION section to CHANGELOG.md"
SECTION_FILE="$(mktemp "${TMPDIR:-/tmp}/release-section.XXXXXX")"
{
    printf '## %s — %s\n\n' "$TAG" "$(date -u +%Y-%m-%d)"
    # Normalize to exactly one trailing blank line, regardless of how the
    # notes ended, so the separator before the next "## v..." header is
    # always present — command substitution strips all trailing newlines,
    # then we add exactly one blank line back.
    printf '%s\n\n' "$(cat "$NOTES_FILE")"
} > "$SECTION_FILE"

if [[ -f CHANGELOG.md ]]; then
    {
        printf '# Changelog\n\n'
        cat "$SECTION_FILE"
        # Drop the existing first line only when it is the header we are about
        # to re-emit. Anything else — a hand-written preamble, a differently
        # worded title — is content, and stripping it would lose it silently.
        if [[ "$(head -1 CHANGELOG.md)" == "# Changelog" ]]; then
            tail -n +2 CHANGELOG.md | sed '/./,$!d'
        else
            sed '/./,$!d' CHANGELOG.md
        fi
    } > CHANGELOG.md.new
else
    {
        printf '# Changelog\n\n'
        cat "$SECTION_FILE"
    } > CHANGELOG.md.new
fi
# The section above deliberately ends in a blank line so consecutive releases stay
# separated. When the new section is the last thing in the file that leaves a
# trailing blank line, and the repo's own end-of-file-fixer pre-commit hook
# rewrites the file to strip it — which fails the release commit and rolls the
# whole release back. Normalize the assembled file to exactly one trailing
# newline: command substitution strips every trailing newline, then add one back.
# Internal blank lines, including the separators between sections, are untouched.
printf '%s\n' "$(cat CHANGELOG.md.new)" > CHANGELOG.md
rm -f -- CHANGELOG.md.new "$SECTION_FILE"

# ---- commit, tag, push -----------------------------------------------------

info "Committing the release"
git add pyproject.toml CHANGELOG.md
if [[ -f uv.lock ]]; then
    git add uv.lock
fi
# This subject is load-bearing: head_is_release_commit() matches it literally to
# decide whether a re-run may resume. Reword it and both resume arms stop firing
# (they fall back to the "tag already exists locally" error), so change it there
# too.
git commit -S -s -m "chore(release): $TAG" \
    || die "the release commit failed — see the output above. Either a pre-commit
hook rewrote a staged file (the repo runs end-of-file-fixer and trailing-whitespace,
both of which fail the commit when they change something), or signing failed.
Signing is mandatory: do not retry without it. The worktree is restored below."

info "Creating the signed annotated tag $TAG"
git tag -s "$TAG" -m "Release $TAG" \
    || die "tag creation failed (signing is required)"

# The commit and tag are in place; from here a failure must NOT roll back, so
# that a re-run can resume at the push.
ROLLBACK_TO=""

push_release

create_gh_release

echo
info "Released $TAG."
info "Publish it to the external mirror with: scripts/mirror-release.sh $TAG"
