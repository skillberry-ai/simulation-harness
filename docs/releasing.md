# Releasing and mirroring

This repo is mirrored to a public repo, `github.com/rossoctl/lab-runtime-simulation`.
Releases are the unit of publication: you cut a numbered release here, then
publish a chosen release to the mirror.

## Cut a release

```sh
make release VERSION=0.2.0        # or: ./scripts/release.sh 0.2.0
```

This runs on `main` only, with a clean worktree and in sync with `origin/main`.
It bumps `version` in `pyproject.toml`, prepends a `CHANGELOG.md` section built
from Conventional Commit subjects since the previous tag, commits
`chore(release): v0.2.0`, creates a signed annotated tag, pushes, and creates
the GitHub Release on `github.ibm.com/kaegis/simulation-harness`.

Pushing the tag also triggers `.github/workflows/docker-publish.yml`, which
publishes a version-tagged container image.

Preview without writing anything:

```sh
./scripts/release.sh --dry-run 0.2.0
```

If a run pushes the tag and then fails, re-run the same command — it detects the
pushed tag and resumes at the GitHub Release step. See
[Recovering from a partial run](#recovering-from-a-partial-run).

## Publish a release to the mirror

```sh
make mirror                       # latest release
make mirror VERSION=v0.2.0        # a specific release
make mirror VERSION=0.2.0         # same thing; the v is optional here
```

The mirror ends up with `main` at the release commit plus one auto-generated
notice commit that prepends a detached-mirror banner to `README.md`, and with
every `vX.Y.Z` tag. Everything else is pruned, so in-progress branches are never
published. The script finishes by creating the public release page and resetting
the local clone at `../../rossoctl/lab-runtime-simulation` to the new state.

Both `X.Y.Z` and `vX.Y.Z` are accepted here, because `make release` takes the
bare form. A release tag is strictly `vX.Y.Z`: a pre-release such as `v0.3.0-rc1`
is not a release, is never mirrored, and is never treated as the previous
release. That definition lives once in `scripts/lib/release-tag.sh` and is shared
by both scripts.

Preview the exact ref changes without pushing:

```sh
./scripts/mirror-release.sh --dry-run
```

Before the real push the script asks you to type the target URL, whenever the
target is the built-in default and stdin is a terminal. The push is `--atomic`,
so a rejected ref leaves the mirror untouched rather than half-shaped.

### Escape hatches

| Flag | Use it when |
|---|---|
| `--yes` | Running unattended, or you have already reviewed the dry run and do not want the type-the-URL prompt. |
| `--no-release-page` | `gh` is missing or not authenticated against the public repo. The refs still get published; run again later without the flag to add the page. |
| `--no-reset-local` | There is no local clone of the mirror at `CLONE_DIR`, or you have work there you do not want touched. |

Without `--no-reset-local`, the local clone at `CLONE_DIR` is **hard reset** to
the newly published `origin/main`: any uncommitted work there is lost. The script
warns first if that directory is dirty, and refuses outright if its `origin` is
not the mirror.

## Roll back the mirror

There is no separate rollback path — publish an earlier release:

```sh
make mirror VERSION=v0.1.0
```

## Recovering from a partial run

`scripts/release.sh` does four things that can fail separately. Each state has
exactly one move:

| State | What happened | What to do |
|---|---|---|
| Worktree unchanged, nothing tagged | The commit or the tag failed — most often signing. The script restores the worktree to what preflight found, so nothing is half-applied. | Fix signing, re-run the same command. Do **not** commit leftovers by hand: a version bump with no tag makes that version number permanently unreleasable. |
| Commit and tag exist locally, nothing on the remote | The push failed. It pushes `main` and the tag `--atomic`, so this is the only push-failure state — the tag is never published without its release commit. | Fix the cause and re-run `scripts/release.sh <same version>`. It detects the release commit and its tag at `HEAD` and resumes at the push. Do **not** `git pull` — that puts a merge commit on top of the release commit. |
| Tag pushed, no GitHub Release | `gh release create` failed. | Re-run the same command; it resumes at the GitHub Release step. |
| Everything published | — | Mirror it. |
| `tag vX.Y.Z already exists locally`, and you know a run got part-way | `HEAD` moved after the tag was made (an amend, or a commit on top), so the tag no longer sits on a release commit and resuming declines to fire. | If the tag was never pushed, drop it and start over: `git tag -d vX.Y.Z`, then re-run. If it was already pushed, leave it alone and cut the next version instead — a published tag is a fixed point. |

Resuming is deliberately narrow: both resume paths fire only for a tag this
script created, on a `chore(release): vX.Y.Z` commit at `HEAD` whose
`pyproject.toml` already holds that version. A tag made or pushed by hand is
rejected with `tag vX.Y.Z already exists locally`, since there would be no bump
and no changelog section to publish.

For `scripts/mirror-release.sh` the push is atomic too, so it either fully applied
or changed nothing on the target. A failure after the push (release page, local
clone reset) is safe to retry by re-running the same command.

## Tests

The scripts have an offline test suite that builds throwaway git repos as
fixtures. It touches no network remote and calls no `gh`:

```sh
make test-scripts
```

## Open item: retire the old wrappers

`~/bin/mirror-sync` and `~/work/rossoctl/sync-harness.sh` predate these scripts
and are deliberately kept for now, as a fallback until the first live release has
been cut and mirrored and verified. Once that has happened, they should be
retired so there is only one path to the mirror.
