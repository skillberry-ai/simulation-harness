#!/usr/bin/env bash
#
# release-tag.sh — the one definition of what a release tag is.
# Sourced by scripts/release.sh and scripts/mirror-release.sh.
#
# Both scripts have to agree: release.sh picks the *previous* release tag to
# build notes from, and mirror-release.sh prunes every tag that is not a
# release tag. If the two definitions drifted, mirroring would delete exactly
# the tag release.sh had treated as the last release. Defining it once here
# makes that disagreement impossible rather than merely fixed.
#
# Sourced-only: deliberately sets no shell options, since that would affect
# the caller's shell.

# Extended regex matching a release tag exactly. Pre-release tags such as
# v0.4.0-rc1 deliberately do NOT match: they are not releases, they are not
# mirrored, and they are never the "previous release".
RELEASE_TAG_RE='^v[0-9]+\.[0-9]+\.[0-9]+$'

# Loose glob for pre-filtering `git tag -l` / `git ls-remote` output. Never the
# authority on its own — always post-filter with RELEASE_TAG_RE.
RELEASE_TAG_GLOB='v[0-9]*'

# release_tag_is <tag-or-refname> — true when it names a release tag. Accepts
# either a bare tag name or a refs/tags/... refname.
release_tag_is() {
    [[ "${1#refs/tags/}" =~ $RELEASE_TAG_RE ]]
}

# release_tag_latest — highest local release tag by version sort, or empty when
# there are none. Never fails, so callers under `set -e` can assign it directly.
release_tag_latest() {
    git tag -l "$RELEASE_TAG_GLOB" \
        | { grep -E "$RELEASE_TAG_RE" || true; } \
        | sort -V | tail -1
}
