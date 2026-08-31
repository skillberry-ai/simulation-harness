#!/usr/bin/env bash
#
# release-notes.sh — build markdown release notes from Conventional Commit
# subjects in a git range. Sourced by scripts/release.sh.
#
# Not executable on its own and deliberately free of side effects: it only
# reads git history and writes to stdout, which is what makes it testable.
# Sourced-only: deliberately sets no shell options, since that would affect
# the caller's shell.

# Commit types, in the order their sections appear in the notes.
RELEASE_NOTES_TYPES=(feat fix perf refactor docs test build ci chore)

# release_notes_heading <type> — section heading for a commit type.
release_notes_heading() {
    case "$1" in
        feat)     printf 'Features\n' ;;
        fix)      printf 'Fixes\n' ;;
        perf)     printf 'Performance\n' ;;
        refactor) printf 'Refactoring\n' ;;
        docs)     printf 'Documentation\n' ;;
        test)     printf 'Tests\n' ;;
        build)    printf 'Build\n' ;;
        ci)       printf 'CI\n' ;;
        chore)    printf 'Chores\n' ;;
        breaking) printf 'Breaking changes\n' ;;
        *)        printf 'Other\n' ;;
    esac
}

# _release_notes_is_conventional <subject> — true when the subject opens with a
# known type, an optional (scope), an optional ! and a colon.
_release_notes_is_conventional() {
    local subject="$1" type
    for type in "${RELEASE_NOTES_TYPES[@]}"; do
        if [[ "$subject" =~ ^"$type"(\([^\)]*\))?!?: ]]; then
            return 0
        fi
    done
    return 1
}

# _release_notes_breaking_footer <sha> — the prose of a `BREAKING CHANGE:` (or
# `BREAKING-CHANGE:`) footer, folded onto one line, or empty when there is none.
# Folding matters because the footer is usually wrapped across several lines but
# has to become one markdown bullet. Collection stops at the first blank line so
# that trailers below it (Signed-off-by, Assisted-By) never leak into the notes.
_release_notes_breaking_footer() {
    git show -s --format='%B' "$1" | awk '
        !done_one && /^BREAKING[ -]CHANGE:/ {
            sub(/^BREAKING[ -]CHANGE:[[:space:]]*/, "")
            buf = $0; collecting = 1; next
        }
        collecting {
            if ($0 ~ /^[[:space:]]*$/) { collecting = 0; done_one = 1; next }
            buf = buf " " $0
        }
        END {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", buf)
            if (buf != "") print buf
        }
    '
}

# generate_release_notes <range> — print markdown notes for <range>, grouped by
# type in RELEASE_NOTES_TYPES order with unparseable subjects under "Other".
# Merge commits are excluded. Prints nothing for an empty range.
generate_release_notes() {
    local range="$1"
    local type heading subject scope desc sha footer bang text i
    local -a subjects=() shas=() bucket=() breaking=()

    mapfile -t subjects < <(git log --no-merges --reverse --format='%s' "$range")
    (( ${#subjects[@]} )) || return 0
    mapfile -t shas < <(git log --no-merges --reverse --format='%H' "$range")

    # Breaking changes lead the notes: they are the only entries a reader has to
    # act on before upgrading. A commit declares one either with `!` before the
    # colon or with a BREAKING CHANGE footer. When a footer is present its prose
    # wins, because it says what the reader must *do*, whereas the subject only
    # says what changed. Breaking commits still appear under their own type
    # below, so this section adds emphasis without removing anything.
    for i in "${!subjects[@]}"; do
        subject="${subjects[$i]}"
        sha="${shas[$i]}"
        footer="$(_release_notes_breaking_footer "$sha")"
        scope=""
        bang=""
        desc="$subject"
        # Matched inline rather than via a helper returning joined fields: tab is
        # an IFS whitespace character, so `read` would collapse the empty scope
        # and `!` fields and shift the description into the wrong variable.
        for type in "${RELEASE_NOTES_TYPES[@]}"; do
            if [[ "$subject" =~ ^"$type"(\([^\)]*\))?(!)?:[[:space:]]*(.*)$ ]]; then
                scope="${BASH_REMATCH[1]}"
                scope="${scope#(}"
                scope="${scope%)}"
                bang="${BASH_REMATCH[2]}"
                desc="${BASH_REMATCH[3]}"
                break
            fi
        done
        [[ -n "$bang" || -n "$footer" ]] || continue
        if [[ -n "$footer" ]]; then
            text="$footer"
        else
            text="$desc"
        fi
        if [[ -n "$scope" ]]; then
            breaking+=("**${scope}:** ${text}")
        else
            breaking+=("$text")
        fi
    done

    if (( ${#breaking[@]} )); then
        printf '### %s\n\n' "$(release_notes_heading breaking)"
        printf -- '- %s\n' "${breaking[@]}"
        printf '\n'
    fi

    for type in "${RELEASE_NOTES_TYPES[@]}" other; do
        bucket=()
        for subject in "${subjects[@]}"; do
            if [[ "$type" == other ]]; then
                if ! _release_notes_is_conventional "$subject"; then
                    bucket+=("$subject")
                fi
                continue
            fi
            if [[ "$subject" =~ ^"$type"(\([^\)]*\))?!?:[[:space:]]*(.*)$ ]]; then
                scope="${BASH_REMATCH[1]}"
                desc="${BASH_REMATCH[2]}"
                scope="${scope#(}"
                scope="${scope%)}"
                if [[ -n "$scope" ]]; then
                    bucket+=("**${scope}:** ${desc}")
                else
                    bucket+=("$desc")
                fi
            fi
        done
        (( ${#bucket[@]} )) || continue
        heading="$(release_notes_heading "$type")"
        printf '### %s\n\n' "$heading"
        printf -- '- %s\n' "${bucket[@]}"
        printf '\n'
    done
}
