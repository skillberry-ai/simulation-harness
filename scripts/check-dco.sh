#!/usr/bin/env bash
#
# check-dco.sh — verify every commit in a range carries a matching DCO sign-off.
#
# A commit passes when its message has a `Signed-off-by: Name <email>` trailer
# whose name and email match the commit's own author, compared case-insensitively
# and with surrounding whitespace trimmed. That is what CONTRIBUTING.md promises,
# so it is what this enforces: a sign-off naming someone other than the author
# certifies nothing about the author.
#
# Merge commits and bot commits are exempt, matching the convention used by the
# DCO GitHub App: a merge commit contributes no authored patch, and a bot cannot
# make the certification the DCO describes.
#
# Usage:
#   scripts/check-dco.sh <base-ref> <head-ref>
#
# Checks the commits reachable from <head-ref> but not from <base-ref>. Because
# that range subtracts everything the base branch already carries, a base branch
# that has advanced since the branch was cut drags nothing extra in.
# Requires full history: in CI use actions/checkout with fetch-depth: 0.
#
# Exit codes:
#   0  every checked commit carries a matching sign-off
#   1  at least one commit does not
#   2  bad invocation, or history too incomplete to resolve a ref
set -euo pipefail

PROG="${0##*/}"

err()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
# The only fatal error this script raises is a caller it cannot work with: a ref
# that will not resolve, or the wrong argument count. That is not the same thing
# as an unsigned commit, so it exits 2 and leaves 1 to mean a real finding,
# reported at the bottom of this file.
die_misconfig() { err "$*"; exit 2; }

if [[ $# -ne 2 ]]; then
    printf 'Usage: %s <base-ref> <head-ref>\n' "$PROG" >&2
    exit 2
fi

BASE="$1"
HEAD_REF="$2"

git rev-parse --verify --quiet "$BASE^{commit}" >/dev/null \
    || die_misconfig "cannot resolve base ref: $BASE (is the history complete? use fetch-depth: 0)"
git rev-parse --verify --quiet "$HEAD_REF^{commit}" >/dev/null \
    || die_misconfig "cannot resolve head ref: $HEAD_REF"

# BASE..HEAD_REF is reachable(HEAD_REF) minus reachable(BASE), which is exactly
# the commits this branch adds. Deliberately *not* MERGE_BASE..HEAD_REF: with a
# single merge base the two ranges are identical, since every common ancestor is
# then reachable from that base. With two (a criss-cross history) `git merge-base`
# reports only one, and the range widens to include commits reachable from the
# other -- commits the base branch already carries, so not this branch's to
# certify. See the criss-cross case in scripts/tests/test-check-dco.sh.
RANGE="$BASE..$HEAD_REF"

# Lowercase + collapse surrounding whitespace, so "  Jane Doe " and "jane doe"
# compare equal. Avoids failing a contributor over capitalisation.
normalize() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

checked=0
skipped=0
failed=0
FAILURES=()

while read -r sha; do
    [[ -n "$sha" ]] || continue

    author_name="$(git show -s --format='%an' "$sha")"
    author_email="$(git show -s --format='%ae' "$sha")"
    subject="$(git show -s --format='%s' "$sha")"
    short="$(git rev-parse --short "$sha")"

    # Bots cannot make the DCO certification; the app exempts them too.
    if [[ "$author_name" == *"[bot]" || "$author_email" == *"[bot]@users.noreply.github.com" ]]; then
        skipped=$((skipped + 1))
        continue
    fi

    checked=$((checked + 1))

    want_name="$(normalize "$author_name")"
    want_email="$(normalize "$author_email")"

    matched=0
    found_any=0
    while IFS= read -r trailer; do
        [[ -n "$trailer" ]] || continue
        found_any=1
        # Split "Name <email>" into its two halves.
        t_name="${trailer%%<*}"
        t_email="${trailer#*<}"
        t_email="${t_email%%>*}"
        if [[ "$(normalize "$t_name")" == "$want_name" \
           && "$(normalize "$t_email")" == "$want_email" ]]; then
            matched=1
            break
        fi
    done < <(git show -s --format='%B' "$sha" | sed -n 's/^[[:space:]]*Signed-off-by:[[:space:]]*//p')

    if [[ "$matched" -eq 1 ]]; then
        continue
    fi

    failed=$((failed + 1))
    if [[ "$found_any" -eq 1 ]]; then
        FAILURES+=("$short $subject
      author:   $author_name <$author_email>
      problem:  a Signed-off-by trailer is present but does not match the author")
    else
        FAILURES+=("$short $subject
      author:   $author_name <$author_email>
      problem:  no Signed-off-by trailer")
    fi
done < <(git rev-list --no-merges "$RANGE")

if [[ "$failed" -eq 0 ]]; then
    if [[ "$skipped" -gt 0 ]]; then
        info "DCO ok — $checked commit(s) signed off, $skipped bot commit(s) exempt."
    else
        info "DCO ok — $checked commit(s) signed off."
    fi
    exit 0
fi

err "$failed of $checked commit(s) lack a valid DCO sign-off:"
printf '\n' >&2
for f in "${FAILURES[@]}"; do
    printf '    %s\n\n' "$f" >&2
done

cat >&2 <<'EOF'
Every commit must certify the Developer Certificate of Origin
(https://developercertificate.org/) with a trailer matching its author:

    Signed-off-by: Your Name <your.email@example.com>

Add it going forward with `git commit -s`. To fix the commits above, sign off
the whole branch and force-push:

    git rebase --signoff <base-branch>
    git push --force-with-lease

The trailer's name and email must match your git `user.name` and `user.email`.
EOF
exit 1
