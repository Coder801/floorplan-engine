---
description: Release with the releaser agent: feature → develop, checks, deploy risks, version from commits (cz bump), CHANGELOG, tag on main; you push yourself
---

Start the `releaser` subagent (Agent, subagent_type: releaser) with this task: cut a release
following its instructions. Pass it:

- the increment, if the user asked for one (`patch` or `minor`);
- the `git rev-parse HEAD` hash, if the `verify` skill passed in this session after the last edit
  (so it does not run the checks again); otherwise say the checks have not run.
$ARGUMENTS

Do not run `flow.py`, commit or push yourself. Pass the agent's full summary to the user: version
and tag, the CHANGELOG section, what to do before and after the push, and the push command.
Pushing is up to the user.
