from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from floorplan_engine.cli import app
from floorplan_engine.drawing.symbols import SYMBOLS

runner = CliRunner()


def test_symbols_export(tmp_path: Path) -> None:
    result = runner.invoke(app, ["symbols", str(tmp_path / "sym")])
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "sym").glob("*.dxf"))) == len(SYMBOLS)


def test_load_env_reads_dotenv_without_overriding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env — в окружение: комментарии и кавычки снимаются, заданное в окружении — главнее."""
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
    load_env(tmp_path / "нет.env")  # файла нет — ничего
