#!/usr/bin/env bash
#
# mirror-release.sh — publish one release of this repo to the external mirror.
#
# Bare-mirror-clones the internal repo into a temp directory, repoints main at
# the chosen release tag, deletes every other branch and every non-release tag,
# prepends a detached-mirror notice to README.md, then force-pushes with
# --prune so the mirror contains exactly that release. Finally creates the
# public release page and refreshes the local clone of the mirror.
#
# Rolling back is just running this again with an earlier tag.
#
# Usage:
#   scripts/mirror-release.sh [options] [vX.Y.Z]
#
set -euo pipefail

PROG="${0##*/}"

err()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

REPO_ROOT="$(git rev-parse --show-toplevel)" || die "not inside a git repository"

: "${SOURCE:=git@github.ibm.com:kaegis/simulation-harness.git}"
: "${TARGET:=git@github.com:rossoctl/lab-runtime-simulation.git}"
: "${CLONE_DIR:=$REPO_ROOT/../../rossoctl/lab-runtime-simulation}"
: "${SOURCE_GH_REPO:=github.ibm.com/kaegis/simulation-harness}"
: "${TARGET_GH_REPO:=github.com/rossoctl/lab-runtime-simulation}"

RELEASE_TAG_RE='^v[0-9]+\.[0-9]+\.[0-9]+$'

usage() {
    cat >&2 <<EOF
Usage: $PROG [options] [vX.Y.Z]

Publish release vX.Y.Z of $SOURCE to $TARGET. With no version, uses the
highest release tag on the source.

The mirror ends up with main at the release commit (plus a notice commit on
top) and every vX.Y.Z tag. All other branches and tags are pruned, so
in-progress work is never published.

Options:
  --dry-run           Stop after the dry-run push; change nothing.
  --no-reset-local    Skip refreshing the local clone at CLONE_DIR.
  --no-release-page   Skip creating the GitHub release on the mirror.
  -h, --help          Show this help and exit.

Environment overrides (used by scripts/tests/test-mirror-release.sh):
  SOURCE, TARGET, CLONE_DIR, SOURCE_GH_REPO, TARGET_GH_REPO
EOF
    exit "${1:-2}"
}

DRY_RUN=0
RESET_LOCAL=1
RELEASE_PAGE=1
REF=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)         DRY_RUN=1; shift ;;
        --no-reset-local)  RESET_LOCAL=0; shift ;;
        --no-release-page) RELEASE_PAGE=0; shift ;;
        -h|--help)         usage 0 ;;
        --)                shift; break ;;
        -*)                die "unknown option: $1" ;;
        *)                 [[ -z "$REF" ]] || die "unexpected extra argument: $1"
                           REF="$1"; shift ;;
    esac
done

[[ "$SOURCE" != "$TARGET" ]] || die "source and target are identical — refusing to mirror a repo onto itself"
command -v git >/dev/null 2>&1 || die "git is not installed or not on PATH"
if (( RELEASE_PAGE )); then
    command -v gh >/dev/null 2>&1 || die "gh is not installed or not on PATH (or pass --no-release-page)"
fi

# ---- cleanup ---------------------------------------------------------------

WORKDIR=""
cleanup() {
    if [[ -n "$WORKDIR" && -d "$WORKDIR" ]]; then
        rm -rf -- "$WORKDIR"
    fi
}
trap cleanup EXIT INT TERM

# ---- preflight -------------------------------------------------------------

info "Verifying access to source: $SOURCE"
git ls-remote --quiet "$SOURCE" >/dev/null 2>&1 \
    || die "cannot read source repo (check URL and credentials): $SOURCE"

info "Verifying access to target: $TARGET"
if ! git ls-remote --quiet "$TARGET" >/dev/null 2>&1; then
    warn "cannot currently read target repo: $TARGET"
    warn "expected if the target is brand new/empty; otherwise check the URL and push credentials."
fi

if (( RESET_LOCAL )) && [[ ! -d "$CLONE_DIR/.git" ]]; then
    die "local clone of the mirror not found at $CLONE_DIR (or pass --no-reset-local)"
fi

# ---- resolve the release tag ----------------------------------------------

if [[ -z "$REF" ]]; then
    # Filter with grep rather than an ls-remote pattern: ls-remote's fnmatch
    # handling of character classes varies, and the regex is the same one used to
    # validate an explicit argument. `|| true` keeps the empty case out of set -e
    # so the die below reports it properly.
    REF="$(
        git ls-remote --tags --refs "$SOURCE" 'refs/tags/v*' \
            | awk '{ sub(/^refs\/tags\//, "", $2); print $2 }' \
            | grep -E "$RELEASE_TAG_RE" \
            | sort -V | tail -1 || true
    )"
    [[ -n "$REF" ]] || die "no vX.Y.Z tags on $SOURCE — cut one first with scripts/release.sh"
    info "No release given; using the latest: $REF"
fi

[[ "$REF" =~ $RELEASE_TAG_RE ]] || die "'$REF' is not a release tag (expected vX.Y.Z)"
git ls-remote --exit-code --tags --refs "$SOURCE" "refs/tags/$REF" >/dev/null 2>&1 \
    || die "tag $REF not found on $SOURCE"

# ---- bare mirror clone ----------------------------------------------------

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/mirror-release.XXXXXXXX")"
MIRROR_DIR="$WORKDIR/repo.git"

info "Cloning source as a bare mirror into: $MIRROR_DIR"
git clone --quiet --mirror -- "$SOURCE" "$MIRROR_DIR" || die "failed to clone source repo"

cd "$MIRROR_DIR"

# Push to TARGET; fetch stays on SOURCE.
git remote set-url --push origin "$TARGET"

# A --mirror clone sets remote.origin.mirror=true, which makes a plain push
# behave like --mirror and reject explicit refspecs. Turn it off so the
# refspecs below take effect.
git config remote.origin.mirror false

# Only branches and tags. A --mirror clone also picks up the server's read-only
# hidden refs (GitHub's refs/pull/*), and pushing those is rejected outright.
MIRROR_REFSPECS=( 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' )

# ---- shape the refs to publish -------------------------------------------

release_commit="$(git rev-parse "refs/tags/$REF^{commit}")"

info "Pointing main at $REF ($release_commit)"
git update-ref refs/heads/main "$release_commit"

while read -r ref; do
    if [[ "$ref" != "refs/heads/main" ]]; then
        git update-ref -d "$ref"
    fi
done < <(git for-each-ref --format='%(refname)' refs/heads)

while read -r ref; do
    if [[ ! "${ref#refs/tags/}" =~ $RELEASE_TAG_RE ]]; then
        git update-ref -d "$ref"
    fi
done < <(git for-each-ref --format='%(refname)' refs/tags)

# ---- detached-mirror notice ----------------------------------------------

# Prepend the notice to README.md on main, in place, before the push. Operates
# purely via git plumbing because the mirror is bare. The banner lives in a
# commit layered on top of the freshly-cloned release commit — which never
# carries the banner itself — so it is re-applied on every sync rather than
# stacking up.
apply_notice() {
    local ref="refs/heads/main"
    local index="$WORKDIR/notice.index"
    local blob tree parent new_commit

    info "Prepending the detached-mirror notice to README.md on main"

    rm -f -- "$index"
    blob="$(
        {
            printf "> **Note:** This is a detached mirror of \`%s\`, " "$SOURCE"
            printf "published from release \`%s\`. " "$REF"
            printf 'Any commits made here will be overridden when the next sync happens.\n\n'
            if git cat-file -e "$ref:README.md" 2>/dev/null; then
                git cat-file -p "$ref:README.md"
            fi
        } | git hash-object -w --stdin
    )" || die "failed to hash the new README.md content"

    GIT_INDEX_FILE="$index" git read-tree "$ref" || die "failed to read tree for main"
    GIT_INDEX_FILE="$index" git update-index --add --cacheinfo "100644,$blob,README.md" \
        || die "failed to stage README.md"
    tree="$(GIT_INDEX_FILE="$index" git write-tree)" || die "failed to write tree"
    rm -f -- "$index"

    parent="$(git rev-parse "$ref")"
    new_commit="$(
        GIT_AUTHOR_NAME="mirror-release" GIT_AUTHOR_EMAIL="mirror-release@localhost" \
        GIT_COMMITTER_NAME="mirror-release" GIT_COMMITTER_EMAIL="mirror-release@localhost" \
        git commit-tree "$tree" -p "$parent" \
            -m "docs: detached-mirror notice for $REF (auto-added by mirror-release)"
    )" || die "failed to create the notice commit"

    git update-ref "$ref" "$new_commit" || die "failed to point main at the notice commit"
}

apply_notice

# ---- summary and dry-run push --------------------------------------------

branch_count="$(git for-each-ref --format='%(refname)' refs/heads | wc -l | tr -d ' ')"
tag_count="$(git for-each-ref --format='%(refname)' refs/tags | wc -l | tr -d ' ')"

echo
info "Summary of what will be MIRRORED:"
printf '    Source  : %s\n' "$SOURCE"
printf '    Target  : %s\n' "$TARGET"
printf '    Release : %s\n' "$REF"
printf '    Refs    : %s branch(es), %s tag(s)\n' "$branch_count" "$tag_count"
echo
warn "This force-pushes main and all release tags to the target."
warn "Any branches or tags on the target that are not in this set WILL BE DELETED."
echo

info "Performing a dry-run push (no changes made yet)..."
echo
git push --prune --force --dry-run origin "${MIRROR_REFSPECS[@]}" \
    || die "dry-run push failed — aborting before any changes were made"
echo

if (( DRY_RUN )); then
    info "dry run: stopping here. Nothing was pushed."
    exit 0
fi

# ---- the real push -------------------------------------------------------

info "Force-pushing $REF to the target..."
git push --prune --force origin "${MIRROR_REFSPECS[@]}" \
    || die "push failed — the target may be partially updated; re-run to retry"
info "Target is now an exact mirror of release $REF."

# ---- public release page -------------------------------------------------

if (( RELEASE_PAGE )); then
    if gh release view "$REF" -R "$TARGET_GH_REPO" >/dev/null 2>&1; then
        info "Release page for $REF already exists on the mirror — leaving it alone."
    else
        body="$(gh release view "$REF" -R "$SOURCE_GH_REPO" --json body -q .body 2>/dev/null || true)"
        info "Creating the release page on $TARGET_GH_REPO"
        if [[ -n "$body" ]]; then
            gh release create "$REF" -R "$TARGET_GH_REPO" --title "$REF" --notes "$body" \
                || warn "gh release create failed; the refs are published — re-run to retry the page"
        else
            warn "no release notes found on $SOURCE_GH_REPO for $REF; generating them from commits"
            gh release create "$REF" -R "$TARGET_GH_REPO" --title "$REF" --generate-notes \
                || warn "gh release create failed; the refs are published — re-run to retry the page"
        fi
    fi
fi

# ---- refresh the local clone --------------------------------------------

if (( RESET_LOCAL )); then
    info "Refreshing the local clone at $CLONE_DIR (fetch + reset --hard origin/main)"
    git -C "$CLONE_DIR" fetch origin || die "failed to fetch in $CLONE_DIR"
    git -C "$CLONE_DIR" reset --hard origin/main || die "failed to reset $CLONE_DIR"
fi

echo
info "Published $REF to $TARGET."
