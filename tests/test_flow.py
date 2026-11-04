"""Branches and releases (scripts/flow.py): feature off develop with changes, integrate is rebase
and fast-forward, release is main ← develop, cz bump, develop ← main. On a temporary repository."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("flow", ROOT / "scripts" / "flow.py")
assert spec is not None and spec.loader is not None
flow = importlib.util.module_from_spec(spec)
sys.modules["flow"] = flow
spec.loader.exec_module(flow)

PYPROJECT = """[project]
name = "kv"
version = "0.1.0"

[tool.commitizen]
name = "cz_conventional_commits"
version_provider = "pep621"
tag_format = "v$version"
annotated_tag = true
major_version_zero = true
update_changelog_on_bump = true
"""


def run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit(repo: Path, message: str, name: str = "a.txt") -> None:
    (repo / name).write_text(message, encoding="utf-8")
    run(repo, "add", name)
    run(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """main with pyproject and develop off it; this repository's hooks do not apply here."""
    repo = tmp_path / "kv"
    repo.mkdir()
    run(repo, "init", "-q", "-b", "main")
    run(repo, "config", "user.name", "Test")
    run(repo, "config", "user.email", "test@example.com")
    (repo / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    run(repo, "add", "pyproject.toml")
    run(repo, "commit", "-q", "-m", "chore: init")
    run(repo, "branch", "develop")
    run(repo, "switch", "-q", "develop")
    return repo


def test_feature_branch_keeps_uncommitted_changes(repo: Path) -> None:
    (repo / "new.txt").write_text("x", encoding="utf-8")
    assert flow.feature("zoom", repo) == "feature/zoom"
    assert flow.current_branch(repo) == "feature/zoom"
    assert "?? new.txt" in run(repo, "status", "--porcelain")
    with pytest.raises(flow.FlowError, match="уже есть"):
        run(repo, "switch", "-q", "develop")
        flow.feature("zoom", repo)
    with pytest.raises(flow.FlowError, match="латиница"):
        flow.feature("Зум", repo)
    run(repo, "switch", "-q", "main")
    with pytest.raises(flow.FlowError, match="develop"):
        flow.feature("other", repo)


def test_integrate_rebases_and_fast_forwards_develop(repo: Path) -> None:
    flow.feature("zoom", repo)
    commit(repo, "feat: zoom", "zoom.txt")
    run(repo, "switch", "-q", "develop")
    commit(repo, "fix: other", "other.txt")  # develop moved ahead: a rebase is needed
    run(repo, "switch", "-q", "feature/zoom")
    assert flow.integrate(repo) == "feature/zoom"
    assert flow.current_branch(repo) == "develop"
    log = run(repo, "log", "--format=%s", "-3").splitlines()
    assert log == ["feat: zoom", "fix: other", "chore: init"]  # linear, feat on top
    assert not flow.branch_exists("feature/zoom", repo)
    with pytest.raises(flow.FlowError, match="feature/"):
        flow.integrate(repo)


def test_integrate_requires_clean_tree_and_stops_on_conflict(repo: Path) -> None:
    flow.feature("one", repo)
    (repo / "dirty.txt").write_text("x", encoding="utf-8")
    with pytest.raises(flow.FlowError, match="незакоммиченные"):
        flow.integrate(repo)
    (repo / "dirty.txt").unlink()
    commit(repo, "feat: one", "same.txt")
    run(repo, "switch", "-q", "develop")
    commit(repo, "feat: two", "same.txt")  # the same file: conflict
    run(repo, "switch", "-q", "feature/one")
    with pytest.raises(flow.FlowError, match="конфликт"):
        flow.integrate(repo)
    run(repo, "rebase", "--abort")
    assert flow.current_branch(repo) == "feature/one"


def test_release_bumps_on_main_and_syncs_develop(repo: Path) -> None:
    with pytest.raises(flow.FlowError):
        flow.release(repo)  # nothing to release: no feat/fix after init
    commit(repo, "feat: zoom", "zoom.txt")
    flow.release(repo, dry_run=True)
    assert run(repo, "tag") == ""  # dry-run changes nothing
    flow.release(repo)
    assert flow.current_branch(repo) == "develop"
    assert run(repo, "tag") == "v0.2.0"
    assert run(repo, "rev-parse", "main") == run(repo, "rev-parse", "develop")
    assert 'version = "0.2.0"' in (repo / "pyproject.toml").read_text(encoding="utf-8")
    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## v0.2.0" in changelog and "### Feat" in changelog and "- zoom" in changelog
    assert run(repo, "log", "--format=%s", "-1").startswith("bump: version 0.1.0 → 0.2.0")


def test_release_increment_overrides_commits(repo: Path) -> None:
    """feat gives a minor version, --increment patch gives a patch."""
    commit(repo, "feat: zoom", "zoom.txt")
    flow.release(repo, increment="patch")
    assert run(repo, "tag") == "v0.1.1"


def test_release_refuses_main_ahead_of_develop(repo: Path) -> None:
    run(repo, "switch", "-q", "main")
    commit(repo, "fix: hot", "hot.txt")
    run(repo, "switch", "-q", "develop")
    with pytest.raises(flow.FlowError, match="git merge main"):
        flow.release(repo)
    run(repo, "switch", "-q", "main")
    with pytest.raises(flow.FlowError, match="develop"):
        flow.release(repo)


def test_free_develop_removes_a_forgotten_worktree(repo: Path, tmp_path: Path) -> None:
    run(repo, "switch", "-q", "-c", "feature/x")
    run(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "develop")
    flow.free_develop(repo)
    assert not (tmp_path / "wt").exists()
    run(repo, "switch", "-q", "develop")


def test_free_develop_keeps_a_worktree_with_changes(repo: Path, tmp_path: Path) -> None:
    run(repo, "switch", "-q", "-c", "feature/x")
    run(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "develop")
    (tmp_path / "wt" / "work.txt").write_text("x", encoding="utf-8")
    with pytest.raises(flow.FlowError):
        flow.free_develop(repo)
    assert (tmp_path / "wt" / "work.txt").exists()


def _with_origin(repo: Path, tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    run(tmp_path, "init", "-q", "--bare", str(origin))
    run(repo, "remote", "add", "origin", str(origin))
    return origin


def test_ship_integrates_releases_and_pushes(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = _with_origin(repo, tmp_path)
    monkeypatch.setattr(flow, "CHECKS", ("true",))
    flow.feature("zoom", repo)
    commit(repo, "feat: zoom", "zoom.txt")
    flow.ship(repo, increment="patch", yes=True)
    assert flow.current_branch(repo) == "develop"
    assert not flow.branch_exists("feature/zoom", repo)
    assert run(origin, "tag") == "v0.1.1"
    assert run(origin, "rev-parse", "main") == run(repo, "rev-parse", "main")
    assert run(origin, "rev-parse", "develop") == run(repo, "rev-parse", "develop")


def test_ship_stops_on_a_failed_check(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = _with_origin(repo, tmp_path)
    monkeypatch.setattr(flow, "CHECKS", ("false",))
    commit(repo, "feat: zoom", "zoom.txt")
    with pytest.raises(flow.FlowError, match="проверка"):
        flow.ship(repo, yes=True)
    assert run(repo, "tag") == ""  # no release, nothing pushed
    assert run(origin, "for-each-ref") == ""


def test_ship_refuses_changes_and_a_no_answer(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin = _with_origin(repo, tmp_path)
    monkeypatch.setattr(flow, "CHECKS", ())
    commit(repo, "feat: zoom", "zoom.txt")
    (repo / "dirty.txt").write_text("x", encoding="utf-8")
    with pytest.raises(flow.FlowError, match="незакоммиченные"):
        flow.ship(repo, yes=True)
    (repo / "dirty.txt").unlink()
    monkeypatch.setattr("builtins.input", lambda _: "n")
    with pytest.raises(flow.FlowError, match="отменено"):
        flow.ship(repo)
    assert run(repo, "tag") == ""
    assert run(origin, "for-each-ref") == ""
