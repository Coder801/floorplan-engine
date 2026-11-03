"""There is one product version: the Python package (`floorplan_engine.__version__`,
pyproject.toml) and the viewer page (web/package.json, shown in the viewer settings)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from floorplan_engine import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_versions_agree() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    web = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__
    assert web["version"] == __version__
