---
description: Release from develop: version from commits (cz bump), CHANGELOG, tag on main; you push yourself
---

Release following `docs/development.md`, "Branches and releases". Do not push anything yourself.

1. Make sure you are on `develop` and the tree is clean (`git status --short`). If not on `develop`
   or there are changes, stop and say: run `/commit` first.
2. Run the `verify` skill. If it fails, do not release; show what failed.
3. Run `uv run python scripts/flow.py release --dry-run` and show the user which version it will
   produce. If there is "nothing to release" (no `feat`/`fix` since the last tag), say so and stop.
4. Run `uv run python scripts/flow.py release`: develop → main fast-forward, `cz bump` (version
   files, `CHANGELOG.md`, a `bump: …` commit, a `vX.Y.Z` tag), develop ← main.
   $ARGUMENTS
5. Result: the version, the tag, the last lines of `CHANGELOG.md`, and a reminder:
   `git push origin main develop --follow-tags`.
