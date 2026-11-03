"""There is one product version: the Python package (`floorplan_engine.__version__`,
pyproject.toml), the viewer page (web/package.json, shown in the viewer settings) and the
platform admin (admin/package.json), with their lock files and uv.lock."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from floorplan_engine import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_versions_agree() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__
    for app in ("web", "admin"):
        package = json.loads((ROOT / app / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / app / "package-lock.json").read_text(encoding="utf-8"))
        assert package["version"] == __version__, app
        assert lock["version"] == __version__, app
        assert lock["packages"][""]["version"] == __version__, app
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    own = next(p for p in uv_lock["package"] if p["name"] == "floorplan-engine")
    assert own["version"] == __version__
