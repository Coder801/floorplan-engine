"""Price lists of a project: the studio list under the project's own one."""

from __future__ import annotations

from pathlib import Path

from floorplan_engine.pipeline import find_prices, load_price_layers


def test_studio_prices_used_when_project_has_none(tmp_path: Path) -> None:
    project = tmp_path / "kv"
    project.mkdir()
    assert find_prices(project) is None
    (tmp_path / "prices.yaml").write_text("items: {}\n", "utf-8")
    assert find_prices(project) == tmp_path / "prices.yaml"
    (project / "prices.yaml").write_text("items: {}\n", "utf-8")
    assert find_prices(project) == project / "prices.yaml"  # the top layer names the notes


def test_project_prices_change_only_their_keys(tmp_path: Path) -> None:
    """Decision 2026-11-25: the studio list is the base, the project's own list wins only for the
    keys it names; terms merge the same way; a broken layer stops the estimate prices."""
    project = tmp_path / "kv"
    project.mkdir()
    assert load_price_layers(project) == (None, [])
    (tmp_path / "prices.yaml").write_text(
        'date: "2026-11"\nitems:\n  work.cable: 45\n  work.mechanism: 125\n  socket_box: 20\n',
        "utf-8",
    )
    studio, issues = load_price_layers(project)
    assert issues == [] and studio is not None and studio.items["work.cable"] == 45
    (project / "prices.yaml").write_text("items:\n  work.mechanism: 100\n", "utf-8")
    merged, issues = load_price_layers(project)
    assert issues == [] and merged is not None
    assert merged.items == {"work.cable": 45, "work.mechanism": 100, "socket_box": 20}
    assert merged.date == "2026-11"  # the project list does not set it: the studio's stays
    (project / "prices.yaml").write_text("items:\n  no.such.item: 1\n", "utf-8")
    broken, issues = load_price_layers(project)
    assert broken is None and issues and issues[0].path == "items.no.such.item"


def test_studio_splice_setting_reaches_every_project(tmp_path: Path) -> None:
    """splice is set once in the studio list (decision 2026-11-25); a project list without it keeps
    the studio's, one that sets it wins, like terms."""
    project = tmp_path / "kv"
    project.mkdir()
    (tmp_path / "prices.yaml").write_text("splice: crimp\nitems:\n  socket_box: 20\n", "utf-8")
    (project / "prices.yaml").write_text("items:\n  socket_box: 25\n", "utf-8")
    merged, issues = load_price_layers(project)
    assert issues == [] and merged is not None and merged.splice == "crimp"
    (project / "prices.yaml").write_text("splice: wago\n", "utf-8")
    merged, _ = load_price_layers(project)
    assert merged is not None and merged.splice == "wago"
    (tmp_path / "prices.yaml").write_text("splice: solder\n", "utf-8")
    broken, issues = load_price_layers(project)
    assert broken is None and issues and issues[0].path == "splice"
