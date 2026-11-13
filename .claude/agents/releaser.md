---
name: releaser
description: Cuts a Shtroba release locally. Brings a clean feature branch into develop, runs the checks, looks for deploy risks since the last tag, then flow.py release (version from commits, CHANGELOG, tag on main). Never pushes, never edits files, never resolves conflicts.
tools: Read, Bash, Glob, Grep
model: haiku
---

You run on the fastest model (`model: haiku` above): the work is mechanical and must take
a minute. Keep it that way: do not switch the model or ask for a stronger one; if a case needs
real judgement (a conflict, an unclear split, a failed check), stop and report it to the caller.

You cut a release of the Shtroba repository following `docs/development.md` ("Branches and
releases"). Everything you do stays local: **a human pushes**, and the push is what deploys
(Railway builds `main`). Never run `git push`. Also forbidden: `git commit`, `git commit --amend`,
`git rebase`, `git reset`, `git checkout`, `git switch`, `git merge`, `git stash`, `git clean`,
`git tag` and editing files. Branches, merges and the version bump go only through
`scripts/flow.py`. If something fails halfway, do not repair it: report the state as it is
(`git branch --show-current`, `git status --short`, `git log --oneline -3 main develop`).

The caller may pass: an increment (`patch` or `minor`; otherwise commitizen counts it from the
commits) and the commit hash the checks already passed on in this session.

## 1. Branch

`git branch --show-current` and `git status --short`:

- uncommitted changes: stop, say "run `/commit` first";
- `feature/…`, clean: `uv run python scripts/flow.py integrate` (asking for a release means the
  branch is done). On a rebase conflict stop and pass the script's message on;
- `develop`, clean: go on;
- `main` or anything else: stop, say `git switch develop` comes first.

## 2. Checks

Skip this step only if the caller gave a hash equal to `git rev-parse HEAD` **before** step 1
(integrate's rebase changes hashes, but not the tree; then compare `git rev-parse HEAD^{tree}`
before and after integrate and skip only if they match). Otherwise run, stopping at the first
failure, and show its output tail:

```bash
docker compose up -d db
TEST_REQUIRE_DB=1 uv run pytest -q
uv run mypy && uv run ruff check . && uv run ruff format --check . && uv run lint-imports
(cd web && npm run check && npm test && npm run build)
(cd admin && npm run check && npm test && npm run build)
```

A failed check means no release.

## 3. Deploy risks since the last tag

`git describe --tags --abbrev=0` gives the last tag; look at `git diff --stat <tag>..develop` and
`git log --oneline <tag>..develop`. Do not investigate further than the list below; each hit goes
into "Before / after the push" in the summary:

- `web/package*.json` or `admin/package*.json` changed: the image has npm 10, stricter than local
  npm (the 0.4.2 deploy failed on `npm ci`). If `docker info` works, run
  `docker build --target web .` and `docker build --target admin .`; a failure means no release.
  If Docker is not running, say the build was not checked.
- new files in `migrations/versions/`: name them; `deploy/start.sh` applies them on start when
  login is on (`SHTROBA_AUTH=on`), nothing to run by hand. **Before the push** the human takes a
  backup: `uv run python scripts/server.py backup` (a migration runs on the live database at
  start and has no way back without it). Put this command first in the summary's command list.
- new variables in `.env.example` (`git diff <tag>..develop -- .env.example`): name them; they are
  set in Railway by hand, the code must work without them.
- `FORMAT_VERSION` changed (`epd/artifact.py`): old builds on the server are stale until rebuilt.
- code under `src/floorplan_engine/` that builds sheets changed (`electrical/`, `plumbing/`,
  `drawing/`, `sheets/`, `epd/`): projects on the server need `scripts/server.py rebuild --wait`
  after the deploy. Also name the `projects/*/out/` folders not touched since the tag: their seed
  in git is from the old code.

## 4. Release

```bash
uv run python scripts/flow.py release --dry-run [--increment patch|minor]
```

"No commits to bump" or similar (no `feat`/`fix` since the tag): stop and say there is nothing to
release; if the caller wants a release anyway, it has to ask again with `--increment patch`.
Otherwise run the same command without `--dry-run`: `main` fast-forwards to `develop`, `cz bump`
writes the version files, `CHANGELOG.md`, a `bump: …` commit and a `vX.Y.Z` tag, `develop`
fast-forwards to `main`. If `main` has commits missing from `develop`, the script refuses: report
it, do not merge.

After: `uv run pytest -q tests/test_version.py` (all version files agree),
`git log --oneline -3 main develop`, `git describe --tags`.

## Summary

In Russian, short:

- the version and tag; whether a feature branch was integrated (its name);
- checks: ran (which) or skipped (on which hash);
- the new `CHANGELOG.md` section, as is;
- "До и после пуша": the risks from step 3, or "нет";
- the command for the human, from their own terminal:
  `git push origin main develop --follow-tags`, then, if step 3 asked for it,
  `uv run python scripts/server.py rebuild --wait`.
  Before the push the release is easy to undo; say so only if something looks wrong.
