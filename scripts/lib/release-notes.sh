#!/usr/bin/env bash
#
# release-notes.sh — build markdown release notes from Conventional Commit
# subjects in a git range. Sourced by scripts/release.sh.
#
# Not executable on its own and deliberately free of side effects: it only
# reads git history and writes to stdout, which is what makes it testable.

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

# generate_release_notes <range> — print markdown notes for <range>, grouped by
# type in RELEASE_NOTES_TYPES order with unparseable subjects under "Other".
# Merge commits are excluded. Prints nothing for an empty range.
generate_release_notes() {
    local range="$1"
    local type heading subject scope desc
    local -a subjects=() bucket=()

    mapfile -t subjects < <(git log --no-merges --reverse --format='%s' "$range")
    (( ${#subjects[@]} )) || return 0

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
