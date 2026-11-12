from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import floorplan_engine
from floorplan_engine.cli import app
from floorplan_engine.drawing.symbols import SYMBOLS

runner = CliRunner()


def test_symbols_export(tmp_path: Path) -> None:
    result = runner.invoke(app, ["symbols", str(tmp_path / "sym")])
    assert result.exit_code == 0, result.output
    # A file per block: the low-voltage cabinet shares the panel block
    assert len(list((tmp_path / "sym").glob("*.dxf"))) == len({s.block for s in SYMBOLS.values()})


def test_load_env_reads_dotenv_without_overriding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env into the environment: comments and quotes are stripped, values already in the
    environment win.
    """
    from floorplan_engine.cli import load_env

    env = tmp_path / ".env"
    env.write_text(
        '# вход\nSHTROBA_T_A=on\nexport SHTROBA_T_B="x y"\nSHTROBA_T_C=1   # гость\n'
        "SHTROBA_T_D=from-file\nбез знака равно\n",
        "utf-8",
    )
    for key in ("SHTROBA_T_A", "SHTROBA_T_B", "SHTROBA_T_C"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SHTROBA_T_D", "from-env")
    load_env(env)
    assert os.environ["SHTROBA_T_A"] == "on"
    assert os.environ["SHTROBA_T_B"] == "x y"
    assert os.environ["SHTROBA_T_C"] == "1"
    assert os.environ["SHTROBA_T_D"] == "from-env"
    for key in ("SHTROBA_T_A", "SHTROBA_T_B", "SHTROBA_T_C"):
        monkeypatch.delenv(key)
    load_env(tmp_path / "нет.env")  # no file: nothing


def test_dev_viewer_factory_reads_projects_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`dev` restarts the API on code changes: the factory takes the projects folder from the
    environment.
    """
    from fastapi.testclient import TestClient

    from floorplan_engine.cli import DEV_PROJECTS_ENV, dev_viewer

    (tmp_path / "kv1").mkdir()
    (tmp_path / "kv1" / "room.yaml").write_text("name: x\n", "utf-8")
    monkeypatch.setenv(DEV_PROJECTS_ENV, str(tmp_path))
    monkeypatch.delenv("SHTROBA_AUTH", raising=False)
    monkeypatch.delenv("SHTROBA_STORAGE", raising=False)  # .env may set db: folders here
    names = [p["name"] for p in TestClient(dev_viewer()).get("/api/projects").json()]
    assert names == ["kv1"]


def test_dev_watches_the_whole_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After code changes uvicorn restarts the API by the factory path: nothing here starts."""
    from floorplan_engine.cli import DEV_PROJECTS_ENV

    runs: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: runs.append((a, k)))
    popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", popen)
    monkeypatch.setattr("shutil.which", lambda name: "npm")
    monkeypatch.setattr("floorplan_engine.cli.load_env", lambda path: None)
    monkeypatch.setenv(DEV_PROJECTS_ENV, "")  # the command sets it: restored after the test
    (tmp_path / "web" / "node_modules").mkdir(parents=True)
    (tmp_path / "web" / "package.json").write_text("{}", "utf-8")
    args = ["dev", "--projects", str(tmp_path), "--web", str(tmp_path / "web")]
    args += ["--admin", str(tmp_path / "admin")]
    assert runner.invoke(app, args).exit_code == 0
    ((target,), options) = runs[0]
    assert popen.call_count == 1  # no admin/ next to it: the viewer page only
    assert options["reload_dirs"] == [str(Path(floorplan_engine.__file__).resolve().parent)]
    module, factory = str(target).split(":")
    assert callable(getattr(importlib.import_module(module), factory))


def test_dev_starts_the_admin_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With admin/ the admin dev server starts next to the page (5173/admin/ proxies to it), and
    Ctrl+C stops both."""
    from floorplan_engine.cli import DEV_PROJECTS_ENV

    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)
    popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", popen)
    monkeypatch.setattr("shutil.which", lambda name: "npm")
    monkeypatch.setattr("floorplan_engine.cli.load_env", lambda path: None)
    monkeypatch.setenv(DEV_PROJECTS_ENV, "")
    for name in ("web", "admin"):
        (tmp_path / name / "node_modules").mkdir(parents=True)
        (tmp_path / name / "package.json").write_text("{}", "utf-8")
    args = ["dev", "--projects", str(tmp_path), "--web", str(tmp_path / "web")]
    args += ["--admin", str(tmp_path / "admin")]
    assert runner.invoke(app, args).exit_code == 0
    assert [c.kwargs["cwd"] for c in popen.call_args_list] == [tmp_path / "web", tmp_path / "admin"]
    assert popen.return_value.terminate.call_count == 2


def test_serve_refuses_a_public_address_without_login(monkeypatch: pytest.MonkeyPatch) -> None:
    # Not the environment: the command reads .env itself, and a developer's has login on
    monkeypatch.setattr("floorplan_engine.cli._viewer_auth", lambda: None)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("сервер запущен"))
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0"])
    assert result.exit_code == 2
    assert "SHTROBA_AUTH" in result.output
