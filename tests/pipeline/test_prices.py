"""Price lists of a project: the studio list under the project's own one."""

from __future__ import annotations

from pathlib import Path

from floorplan_engine.pipeline import find_prices, load_price_layers
from floorplan_engine.pipeline.prices import price_page, save_prices


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


def _text(root: Path) -> str:
    return (root / "prices.yaml").read_text("utf-8")


def test_save_prices_keeps_comments_and_drops_stale_finish_keys(tmp_path: Path) -> None:
    """The edit behind the price page of the database viewer (it saves through a temporary
    prices.yaml): line by line, comments kept; a finish material the list still prices goes away
    on any save; a finish material, an unknown key or a negative price is refused, the file
    unchanged."""
    (tmp_path / "prices.yaml").write_text(
        "# прайс\ncurrency: грн\nitems:\n  work.chase: 200  # узкая\n"
        "  socket: 180  # до 2026-11-27\n",
        "utf-8",
    )
    assert price_page(tmp_path)["stale"] == ["socket"]
    assert save_prices(tmp_path, {"items": {"work.chase": 150, "work.cable": 25}}) == []
    text = _text(tmp_path)
    assert "# прайс" in text and "work.chase: 150  # узкая" in text and "work.cable: 25" in text
    assert "socket:" not in text and price_page(tmp_path)["stale"] == []
    assert save_prices(tmp_path, {"items": {"socket_box": 20, "cable.3x2.5": 70}}) == []
    text = _text(tmp_path)
    assert "socket_box: 20" in text and "cable.3x2.5: 70" in text
    (refused,) = save_prices(tmp_path, {"items": {"socket": 60}})
    assert refused.path == "items.socket" and "чистовой материал" in refused.message
    assert save_prices(tmp_path, {"items": {"no.such": 10}})
    assert save_prices(tmp_path, {"items": {"work.chase": -1}})
    assert _text(tmp_path) == text


def test_save_prices_splice_keeps_its_comment(tmp_path: Path) -> None:
    """Joints in switch flush boxes (PriceList.splice): wago when the file does not say; the line
    keeps its comment, the rest of the file stays."""
    (tmp_path / "prices.yaml").write_text(
        "# прайс\ncurrency: грн\nitems:\n  work.chase: 200  # узкая\n", "utf-8"
    )
    assert price_page(tmp_path)["splice"] == "wago"
    assert save_prices(tmp_path, {"splice": "crimp"}) == []
    text = _text(tmp_path)
    assert text == "# прайс\ncurrency: грн\nsplice: crimp\nitems:\n  work.chase: 200  # узкая\n"
    (tmp_path / "prices.yaml").write_text(
        text.replace("splice: crimp", "splice: crimp  # так монтирует бригада"), "utf-8"
    )
    assert save_prices(tmp_path, {"splice": "wago", "items": {"work.chase": 210}}) == []
    text = _text(tmp_path)
    assert "splice: wago  # так монтирует бригада\n" in text and text.count("splice:") == 1
    assert "work.chase: 210  # узкая" in text
    (bad,) = save_prices(tmp_path, {"splice": "solder", "items": {"work.chase": 1}})
    assert bad.path == "splice" and _text(tmp_path) == text


MARKET = """region: Київ
collected: "2026-11-28"
sources:
  a: { name: "A", url: "https://a.example", date: "2026-11" }
  b: { name: "B", url: "https://b.example" }
items:
  work.wall_hole:
    basis: "сквозное отверстие в стене, бетон, до Ø25"
    quotes:
      a: { price: 160, text: "свердління" }
      b: { price: 80, text: "отвір" }
  work.wall_hole_large:
    quotes:
      b: { price: 300, text: "коронка" }
"""


def test_plumbing_items_on_the_price_page(tmp_path: Path) -> None:
    """The studio list is one for electrical and plumbing: work.wall_hole, retired from the
    electrical estimate on 2026-11-28 (a cable pass), is still a plumbing item — a row of the
    page with its market spread, and the page saves it; a key no estimate counts
    (work.wall_hole_large) has neither."""
    (tmp_path / "prices.yaml").write_text("items:\n  work.wall_hole: 120\n", "utf-8")
    (tmp_path / "market.yaml").write_text(MARKET, "utf-8")
    page = price_page(tmp_path)
    assert page["issues"] == []
    rows = {r["key"]: r for r in page["rows"]}
    hole = rows["work.wall_hole"]
    assert (hole["stage"], hole["kind"], hole["price"]) == ("plumbing", "work", 120)
    assert hole["name"]["ru"] == "Отверстие в перегородке под трубы" and hole["unit"] == "шт"
    assert hole["market"]["n"] == 2 and hole["market"]["median"] == 120
    assert rows["work.cable_pass"]["stage"] == "electrical"
    assert rows["water.collector"]["unit"] == "вых."  # a unit by language: the Russian one
    assert "work.wall_hole_large" not in rows
    assert [s["id"] for s in page["market"]["sources"]] == ["a", "b"]
    # Works first, electrical then plumbing; then materials the same way
    order = [(r["kind"], r["stage"]) for r in page["rows"]]
    assert order == sorted(order, key=lambda ks: (ks[0] != "work", ks[1] != "electrical"))
    assert save_prices(tmp_path, {"items": {"work.wall_hole": 140, "sewer.pipe50": 90}}) == []
    text = _text(tmp_path)
    assert "work.wall_hole: 140" in text and "sewer.pipe50: 90" in text
    (bad,) = save_prices(tmp_path, {"items": {"work.wall_hole": -1}})
    assert bad.path == "items.work.wall_hole"
