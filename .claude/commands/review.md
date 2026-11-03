---
description: Two-pass review of changes: the built-in /code-review (bugs in the diff) and the reviewer agent (domain cases, Shtroba rules, layer boundaries, docs); one combined list of findings
argument-hint: [level low|medium|high] [commit range, for example HEAD~1..]
---

Check the changes with two independent passes and merge the findings. Do not edit code; only report.

Arguments: `$ARGUMENTS`. A first word from `low | medium | high` is the level of the built-in review
(`medium` if not given); the rest is a commit range (`HEAD~1..`, `abc123..def456`). Without a range,
check the uncommitted changes, including new files (`git status --porcelain`, `git diff HEAD`, and
read untracked `??` files in full with Read). After `/commit` there are none left, so give a range.

1. Built-in review: the `code-review` skill with the level and, if given, the range. It looks for
   ordinary correctness bugs in the diff.
2. In parallel, start the `reviewer` subagent (Agent, subagent_type: reviewer) with this task: check
   the same changes (the same range or the uncommitted ones, new files in full) in its own order:
   domain edge cases (both languages `ru`/`uk`, no panel, no scale, ceiling points, neighbouring
   rooms), layer boundaries, project rules, determinism, docs, tests. It does not look for general
   bugs: step 1 did that.
3. Merge both results into one list from most to least serious: file:line, what is wrong, the
   scenario, how to fix it. Merge identical findings and say where each came from
   (`code-review` / `reviewer`). If there are no findings, say so.
