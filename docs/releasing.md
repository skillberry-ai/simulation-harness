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
pushed tag and resumes at the GitHub Release step.

## Publish a release to the mirror

```sh
make mirror                       # latest release
make mirror VERSION=v0.2.0        # a specific release
```

The mirror ends up with `main` at the release commit plus one auto-generated
notice commit that prepends a detached-mirror banner to `README.md`, and with
every `vX.Y.Z` tag. Everything else is pruned, so in-progress branches are never
published. The script finishes by creating the public release page and resetting
the local clone at `../../rossoctl/lab-runtime-simulation` to the new state.

Preview the exact ref changes without pushing:

```sh
./scripts/mirror-release.sh --dry-run
```

## Roll back the mirror

There is no separate rollback path — publish an earlier release:

```sh
make mirror VERSION=v0.1.0
```

## Tests

The scripts have an offline test suite that builds throwaway git repos as
fixtures. It touches no network remote and calls no `gh`:

```sh
make test-scripts
```
