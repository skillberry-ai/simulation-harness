#!/usr/bin/env bash
#
# release-tag.sh — the one definition of what a release tag is.
# Sourced by scripts/release.sh.
#
# release.sh uses it to pick the *previous* release tag to build notes from, so
# the definition of "release tag" has to be stable and stated once. A release
# tag is strictly vX.Y.Z; a pre-release such as v0.3.0-rc1 is not a release and
# is never treated as the previous one.
#
# Sourced-only: deliberately sets no shell options, since that would affect
# the caller's shell.

# Extended regex matching a release tag exactly. Pre-release tags such as
# v0.4.0-rc1 deliberately do NOT match: they are not releases, and they are
# never the "previous release".
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
