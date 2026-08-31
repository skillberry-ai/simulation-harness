# Releasing

Releases are cut with `scripts/release.sh` on `main`. A release tag is strictly
`vX.Y.Z`; a pre-release such as `v0.3.0-rc1` is not a release and is never treated
as the previous one. That definition lives once in `scripts/lib/release-tag.sh`.

## Cut a release

```sh
make release VERSION=0.2.0        # or: ./scripts/release.sh 0.2.0
```

This runs on `main` only, with a clean worktree and in sync with `origin/main`.
It bumps `version` in `pyproject.toml`, re-locks `uv.lock` (which pins the
project's own version, so it would otherwise go stale — `uv` must be on `PATH`),
prepends a `CHANGELOG.md` section built from Conventional Commit subjects since
the previous tag, commits `chore(release): v0.2.0`, creates a signed annotated
tag, pushes, and creates the GitHub Release.

Preview without writing anything:

```sh
./scripts/release.sh --dry-run 0.2.0
```

If a run pushes the tag and then fails, re-run the same command — it detects the
pushed tag and resumes at the GitHub Release step. See
[Recovering from a partial run](#recovering-from-a-partial-run).

The release page is created on `$RELEASE_GH_REPO`, which defaults to
`github.com/skillberry-ai/simulation-harness`. Override it if you are releasing a
fork. `RELEASE_SKIP_GH=1` skips the page entirely, and `RELEASE_REMOTE` selects
the push remote (default `origin`).

## Container images

Cutting a release does not build an image directly — pushing the tag does.
`.github/workflows/docker-publish.yml` triggers on `push` to `main` and on
`tags: ["v*.*.*"]`, so the tag push builds the image and pushes it to
`ghcr.io/<owner>/simulation-harness`. The owner comes from
`github.repository_owner`, so the image name follows whoever owns the repo rather
than being hardcoded.

Because the atomic push carries both `main` and the tag, a single release **fires
the workflow twice** — once for each ref. That is wasteful but harmless; the two
runs tag the image differently.

To build an image locally without involving CI, use `make docker-build`.

## Recovering from a partial run

`scripts/release.sh` does four things that can fail separately. Each state has
exactly one move:

| State | What happened | What to do |
|---|---|---|
| Worktree unchanged, nothing tagged | The commit or the tag failed — most often signing. The script restores the worktree to what preflight found, so nothing is half-applied. | Fix signing, re-run the same command. Do **not** commit leftovers by hand: a version bump with no tag makes that version number permanently unreleasable. |
| Commit and tag exist locally, nothing on the remote | The push failed. It pushes `main` and the tag `--atomic`, so this is the only push-failure state — the tag is never published without its release commit. | Fix the cause and re-run `scripts/release.sh <same version>`. It detects the release commit and its tag at `HEAD` and resumes at the push. Do **not** `git pull` — that puts a merge commit on top of the release commit. |
| Tag pushed, no GitHub Release | `gh release create` failed. | Re-run the same command; it resumes at the GitHub Release step. |
| Everything published | — | Nothing; the tag push builds the image. |
| `tag vX.Y.Z already exists locally`, and you know a run got part-way | `HEAD` moved after the tag was made (an amend, or a commit on top), so the tag no longer sits on a release commit and resuming declines to fire. | If the tag was never pushed, drop it and start over: `git tag -d vX.Y.Z`, then re-run. If it was already pushed, leave it alone and cut the next version instead — a published tag is a fixed point. |

Resuming is deliberately narrow: both resume paths fire only for a tag this
script created, on a `chore(release): vX.Y.Z` commit at `HEAD` whose
`pyproject.toml` already holds that version. A tag made or pushed by hand is
rejected with `tag vX.Y.Z already exists locally`, since there would be no bump
and no changelog section to publish.

## Tests

The scripts have an offline test suite that builds throwaway git repos as
fixtures. It touches no network remote and calls no `gh`:

```sh
make test-scripts
```
