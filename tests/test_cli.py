from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from shtroba.cli import app
from shtroba.symbols import SYMBOLS

runner = CliRunner()


def test_symbols_export(tmp_path: Path) -> None:
    result = runner.invoke(app, ["symbols", str(tmp_path / "sym")])
    assert result.exit_code == 0, result.output
    assert len(list((tmp_path / "sym").glob("*.dxf"))) == len(SYMBOLS)
