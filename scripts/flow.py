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
CHECKS = (  # the verify skill, step 1; admin/ is checked by CI
    "docker compose up -d db",
    "TEST_REQUIRE_DB=1 uv run pytest -q",
    "uv run mypy",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run lint-imports",
    "cd web && npm run check && npm test && npm run build",
)
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


def release(cwd: Path, dry_run: bool = False, increment: str | None = None) -> None:
    """develop → main (fast-forward), cz bump on main, develop ← main (fast-forward)."""
    bump = ("bump", "--yes", *(("--increment", increment.upper()) if increment else ()))
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
    cz(*bump, "--dry-run", cwd=cwd)  # nothing to release: stop before switching branches
    if dry_run:
        return
    git("switch", MAIN, cwd=cwd)
    git("merge", "--ff-only", DEVELOP, cwd=cwd)
    try:
        cz(*bump, cwd=cwd)
    finally:
        git("switch", DEVELOP, cwd=cwd)
    git("merge", "--ff-only", MAIN, cwd=cwd)


def free_develop(cwd: Path) -> None:
    """A forgotten worktree holds develop and git will not switch to it: remove the worktree. One
    with changes stays: git refuses, and the message says so."""
    git("worktree", "prune", cwd=cwd)
    here = Path(git("rev-parse", "--show-toplevel", cwd=cwd)).resolve()
    path = None
    for line in git("worktree", "list", "--porcelain", cwd=cwd).splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree ")).resolve()
        elif line == f"branch refs/heads/{DEVELOP}" and path is not None and path != here:
            git("worktree", "remove", str(path), cwd=cwd)


def run_checks(cwd: Path) -> None:
    for check in CHECKS:
        print(f"flow: {check}", flush=True)
        if subprocess.run(check, shell=True, cwd=cwd).returncode != 0:
            raise FlowError(f"проверка не прошла: {check}")


def ship(
    cwd: Path,
    increment: str | None = None,
    dry_run: bool = False,
    yes: bool = False,
    rebuild: bool = False,
) -> None:
    """Everything after /commit: feature → develop, checks, release, push, rebuild on the server.
    The push happens after one question (--yes: without it)."""
    branch = current_branch(cwd)
    feature_branch = branch.startswith(FEATURE)
    if not feature_branch and branch != DEVELOP:
        raise FlowError(f"нужна ветка {FEATURE}<имя> или {DEVELOP}, сейчас — «{branch}»")
    if not is_clean(cwd):
        raise FlowError("есть незакоммиченные изменения: сначала закоммитьте (/commit)")
    if dry_run:
        print(f"flow: {branch} → {DEVELOP} → проверки → релиз → push {MAIN} {DEVELOP}")
        if not feature_branch:
            release(cwd, dry_run=True, increment=increment)
        return
    free_develop(cwd)
    if feature_branch:
        integrate(cwd)
    run_checks(cwd)
    release(cwd, dry_run=True, increment=increment)
    if not yes and input(f"Выпустить и запушить {MAIN}, {DEVELOP}? [y/N] ").lower() != "y":
        raise FlowError(f"отменено на {DEVELOP}: ветка влита, релиза и пуша нет")
    release(cwd, increment=increment)
    git("push", "origin", MAIN, DEVELOP, "--follow-tags", cwd=cwd)
    if rebuild:
        server = [sys.executable, str(Path(__file__).with_name("server.py")), "rebuild", "--wait"]
        if subprocess.run(server, cwd=cwd).returncode != 0:
            raise FlowError("релиз выложен, но пересборка не удалась: scripts/server.py rebuild")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ветки и релизы: feature, integrate, release")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("feature", help="ветка feature/<имя> от develop")
    p.add_argument("name")
    p = sub.add_parser("integrate", help="feature → develop (rebase, fast-forward)")
    p.add_argument("--keep", action="store_true", help="не удалять ветку")
    p = sub.add_parser("release", help="develop → main, cz bump, develop ← main")
    p.add_argument("--dry-run", action="store_true", help="только показать версию")
    p.add_argument(
        "--increment",
        choices=("patch", "minor"),
        help="задать шаг версии, а не считать по коммитам",
    )
    p = sub.add_parser("ship", help="всё после /commit: вливание, проверки, релиз, пуш")
    p.add_argument("--dry-run", action="store_true", help="только показать план и версию")
    p.add_argument("--increment", choices=("patch", "minor"), help="шаг версии")
    p.add_argument("--yes", action="store_true", help="пушить, не спрашивая")
    p.add_argument(
        "--rebuild", action="store_true", help="дождаться выкладки и пересобрать проекты"
    )
    args = parser.parse_args(argv)
    cwd = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()))
    try:
        if args.command == "feature":
            print(f"ветка {feature(args.name, cwd)}: правки здесь, дальше — /commit")
        elif args.command == "integrate":
            print(f"{integrate(cwd, keep=args.keep)} → {DEVELOP}; пуш: git push origin {DEVELOP}")
        elif args.command == "ship":
            ship(cwd, args.increment, args.dry_run, args.yes, args.rebuild)
        else:
            release(cwd, dry_run=args.dry_run, increment=args.increment)
            if not args.dry_run:
                print(f"релиз готов; пуш: git push origin {MAIN} {DEVELOP} --follow-tags")
    except FlowError as e:
        print(f"flow: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
