#!/usr/bin/env bash
#
# release.sh — cut a numbered release of this repo.
#
# Bumps the version in pyproject.toml, prepends a CHANGELOG.md section built
# from Conventional Commit subjects since the last release, commits and signs
# an annotated tag, pushes, and creates the GitHub Release on the internal repo.
#
# Pushing the tag also triggers .github/workflows/docker-publish.yml, which
# publishes a version-tagged container image.
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
        --)        shift; break ;;
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

: "${RELEASE_REMOTE:=origin}"
: "${RELEASE_GH_REPO:=github.ibm.com/kaegis/simulation-harness}"
: "${RELEASE_SKIP_GH:=0}"

NOTES_FILE="$(mktemp "${TMPDIR:-/tmp}/release-notes.XXXXXX")"
trap 'rm -f -- "$NOTES_FILE"' EXIT

# ---- helpers ---------------------------------------------------------------

# Current version from the first `version = "..."` line in pyproject.toml.
current_version() {
    sed -n 's/^version = "\([^"]*\)"$/\1/p' pyproject.toml | head -1
}

# Highest local release tag, or empty when none exist.
latest_tag() {
    git tag -l 'v[0-9]*.[0-9]*.[0-9]*' | sort -V | tail -1
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

remote_tag_commit=""
ls_remote_out="$(git ls-remote --tags --refs "$RELEASE_REMOTE" "refs/tags/$TAG")" \
    || die "failed to query tags on $RELEASE_REMOTE"
if [[ -n "$ls_remote_out" ]]; then
    remote_tag_commit="$(git rev-parse --verify --quiet "refs/tags/$TAG^{commit}" || true)"
fi

if [[ -n "$remote_tag_commit" && "$remote_tag_commit" == "$(git rev-parse HEAD)" ]]; then
    warn "$TAG already exists on $RELEASE_REMOTE and HEAD is unchanged since — a previous run got this far."
    warn "Resuming at the GitHub release step; nothing will be committed or pushed."
    if [[ -f CHANGELOG.md ]]; then
        changelog_section > "$NOTES_FILE"
    fi
    if [[ ! -s "$NOTES_FILE" ]]; then
        printf 'See CHANGELOG.md.\n' > "$NOTES_FILE"
    fi
    if (( DRY_RUN )); then
        info "dry run: would create the GitHub release for $TAG with:"
        sed 's/^/    /' "$NOTES_FILE"
        exit 0
    fi
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

prev_tag="$(latest_tag)"
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
printf '    Remote       : %s\n' "$RELEASE_REMOTE"
printf '    GitHub repo  : %s\n' "$RELEASE_GH_REPO"
echo
info "Release notes"
sed 's/^/    /' "$NOTES_FILE"
echo

if (( DRY_RUN )); then
    info "dry run: nothing was written. Would bump pyproject.toml, prepend"
    info "CHANGELOG.md, commit 'chore(release): $TAG', tag, push to"
    info "$RELEASE_REMOTE, and create the GitHub release."
    exit 0
fi

# ---- bump pyproject.toml ---------------------------------------------------

info "Setting version to $VERSION in pyproject.toml"
awk -v v="$VERSION" '
    !done && /^version = "/ { sub(/"[^"]*"/, "\"" v "\""); done = 1 }
    { print }
' pyproject.toml > pyproject.toml.new
mv pyproject.toml.new pyproject.toml

[[ "$(current_version)" == "$VERSION" ]] || die "failed to update the version in pyproject.toml"

# ---- prepend the CHANGELOG section ----------------------------------------

info "Prepending the v$VERSION section to CHANGELOG.md"
section="$(mktemp "${TMPDIR:-/tmp}/release-section.XXXXXX")"
{
    printf '## %s — %s\n\n' "$TAG" "$(date -u +%Y-%m-%d)"
    # Normalize to exactly one trailing blank line, regardless of how the
    # notes ended, so the separator before the next "## v..." header is
    # always present — command substitution strips all trailing newlines,
    # then we add exactly one blank line back.
    printf '%s\n\n' "$(cat "$NOTES_FILE")"
} > "$section"

if [[ -f CHANGELOG.md ]]; then
    {
        printf '# Changelog\n\n'
        cat "$section"
        tail -n +2 CHANGELOG.md | sed '/./,$!d'
    } > CHANGELOG.md.new
else
    {
        printf '# Changelog\n\n'
        cat "$section"
    } > CHANGELOG.md.new
fi
mv CHANGELOG.md.new CHANGELOG.md
rm -f -- "$section"

# ---- commit, tag, push -----------------------------------------------------

info "Committing the release"
git add pyproject.toml CHANGELOG.md
git commit -S -s -m "chore(release): $TAG" \
    || die "commit failed (signing is required; do not fall back to unsigned)"

info "Creating the signed annotated tag $TAG"
git tag -s "$TAG" -m "Release $TAG" \
    || die "tag creation failed (signing is required)"

info "Pushing main and $TAG to $RELEASE_REMOTE"
git push "$RELEASE_REMOTE" main "$TAG" \
    || die "push failed; the local commit and tag are intact — fix and re-run"

create_gh_release

echo
info "Released $TAG."
info "Publish it to the external mirror with: scripts/mirror-release.sh $TAG"
