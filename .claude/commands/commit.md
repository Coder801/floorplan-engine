---
description: Commit uncommitted changes with the committer agent (review, split into commits, English message); you push yourself
---

If the changes include code (`src/`, `web/src/`, `tests/`, `migrations/`, `deploy/`) and the checks
have not run in this session since the last edit, run the `verify` skill first. If it fails, do
not commit; show what failed.

Then start the `committer` subagent (Agent, subagent_type: committer) with this task: review the
current uncommitted changes in the repository, split them into independent commits, stage the
right files and commit using its template. It picks the branch itself following
`docs/development.md` ("Branches and releases"): from `develop` it goes through `feature/<name>`
and back, and it never commits to `main`.
$ARGUMENTS

Do not stage, commit or push yourself. Pass the agent's full summary to the user: which commits
landed (hash and title), what was left uncommitted and why, and any questions. Pushing is up to the
user.
