"""Branches and releases (docs/development.md, "Branches and releases", decision 2026-11-03):
`develop` is for development, `feature/<name>` for work, `main` only for tagged releases.
There are no release branches.

  uv run python scripts/flow.py feature <name>      # branch feature/<name> off develop;
                                                    # uncommitted changes move with it
  uv run python scripts/flow.py integrate [--keep]  # feature → develop: rebase onto develop,
                                                    # fast-forward; branch is deleted (--keep: not)
  uv run python scripts/flow.py release [--dry-run] # develop → main fast-forward, cz bump
                                                    # (version, CHANGELOG, tag), develop ← main

Push by hand: `git push origin develop`, after a release `git push origin main develop
--follow-tags`. The script does not resolve rebase conflicts: it stops and leaves the rest to
a human (`git rebase --continue` or `--abort`).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEVELOP = "develop"
MAIN = "main"
FEATURE = "feature/"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class FlowError(Exception):
    """Flow error: a message for a human, no traceback."""


def git(*args: str, cwd: Path, check: bool = True) -> str:
    """Run git and return stdout as a string; on error raise FlowError with stderr."""
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise FlowError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def current_branch(cwd: Path) -> str:
    return git("branch", "--show-current", cwd=cwd)


def is_clean(cwd: Path) -> bool:
    return git("status", "--porcelain", cwd=cwd) == ""


def branch_exists(name: str, cwd: Path) -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
        cwd=cwd,
        capture_output=True,
    )
    return r.returncode == 0


def cz(*args: str, cwd: Path) -> None:
    """commitizen from the same environment as the script (uv run)."""
    r = subprocess.run([sys.executable, "-m", "commitizen", *args], cwd=cwd)
    if r.returncode != 0:
        raise FlowError(f"cz {' '.join(args)}: код {r.returncode}")


def feature(name: str, cwd: Path) -> str:
    """Branch feature/<name> off develop, taking the current changes along. Must be on develop."""
    if not NAME_RE.match(name):
        raise FlowError(f"имя ветки «{name}»: латиница, цифры, «-», «.», «_»")
    branch = current_branch(cwd)
    if branch != DEVELOP:
        raise FlowError(
            f"ветка feature создаётся от {DEVELOP}, сейчас — «{branch}»: git switch {DEVELOP}"
        )
    target = FEATURE + name
    if branch_exists(target, cwd):
        raise FlowError(f"ветка {target} уже есть: git switch {target}")
    git("switch", "-c", target, cwd=cwd)  # uncommitted changes move with us
    return target


def integrate(cwd: Path, keep: bool = False) -> str:
    """feature → develop: rebase onto develop, fast-forward develop, delete the branch."""
    branch = current_branch(cwd)
    if not branch.startswith(FEATURE):
        raise FlowError(f"нужна ветка {FEATURE}<имя>, сейчас — «{branch}»")
    if not is_clean(cwd):
        raise FlowError("есть незакоммиченные изменения: сначала закоммитьте (/commit)")
    r = subprocess.run(["git", "rebase", DEVELOP], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise FlowError(
            f"rebase на {DEVELOP} остановился — решите конфликт и продолжите "
            f"(git rebase --continue) или отмените (git rebase --abort):\n{r.stdout}{r.stderr}"
        )
    git("switch", DEVELOP, cwd=cwd)
    git("merge", "--ff-only", branch, cwd=cwd)
    if not keep:
        git("branch", "-d", branch, cwd=cwd)
    return branch


def release(cwd: Path, dry_run: bool = False) -> None:
    """develop → main (fast-forward), cz bump on main, develop ← main (fast-forward)."""
    branch = current_branch(cwd)
    if branch != DEVELOP:
        raise FlowError(f"релиз — с {DEVELOP}, сейчас — «{branch}»")
    if not is_clean(cwd):
        raise FlowError("есть незакоммиченные изменения: сначала закоммитьте (/commit)")
    if not branch_exists(MAIN, cwd):
        raise FlowError(f"нет ветки {MAIN}")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", MAIN, DEVELOP], cwd=cwd, capture_output=True
    )
    if ancestor.returncode != 0:
        raise FlowError(
            f"в {MAIN} есть коммиты, которых нет в {DEVELOP}: git merge {MAIN}, потом релиз"
        )
    if dry_run:
        cz("bump", "--dry-run", "--yes", cwd=cwd)
        return
    cz("bump", "--dry-run", "--yes", cwd=cwd)  # nothing to release: stop before switching branches
    git("switch", MAIN, cwd=cwd)
    git("merge", "--ff-only", DEVELOP, cwd=cwd)
    try:
        cz("bump", "--yes", cwd=cwd)
    finally:
        git("switch", DEVELOP, cwd=cwd)
    git("merge", "--ff-only", MAIN, cwd=cwd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ветки и релизы: feature, integrate, release")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("feature", help="ветка feature/<имя> от develop")
    p.add_argument("name")
    p = sub.add_parser("integrate", help="feature → develop (rebase, fast-forward)")
    p.add_argument("--keep", action="store_true", help="не удалять ветку")
    p = sub.add_parser("release", help="develop → main, cz bump, develop ← main")
    p.add_argument("--dry-run", action="store_true", help="только показать версию")
    args = parser.parse_args(argv)
    cwd = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()))
    try:
        if args.command == "feature":
            print(f"ветка {feature(args.name, cwd)}: правки здесь, дальше — /commit")
        elif args.command == "integrate":
            print(f"{integrate(cwd, keep=args.keep)} → {DEVELOP}; пуш: git push origin {DEVELOP}")
        else:
            release(cwd, dry_run=args.dry_run)
            if not args.dry_run:
                print(f"релиз готов; пуш: git push origin {MAIN} {DEVELOP} --follow-tags")
    except FlowError as e:
        print(f"flow: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
