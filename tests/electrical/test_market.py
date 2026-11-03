"""Market prices of works (electrical/market.py): sample schema, spread, period; the real
sample projects/market.yaml reads and refers only to estimate items."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from floorplan_engine.electrical.market import (
    MarketSample,
    item_spread,
    period,
    spread,
    used_sources,
)

ROOT = Path(__file__).resolve().parents[2]


def _sample(**over: Any) -> MarketSample:
    data: dict[str, Any] = {
        "region": "Київ",
        "collected": "2026-11-03",
        "sources": {
            "a": {"name": "A", "url": "https://a", "date": "2024"},
            "b": {"name": "B", "url": "https://b", "date": "2026-03-24"},
            "c": {"name": "C", "url": "https://c", "date": "2026-11"},
            "d": {"name": "D", "url": "https://d"},
        },
        "items": {
            "work.chase": {
                "quotes": {
                    "a": {"price": 80, "text": "штроба"},
                    "b": {"price": 200, "text": "штроба"},
                    "c": {"price": 90, "text": "штроба"},
                    "d": {"price": 550, "text": "штроба"},
                }
            }
        },
    }
    data.update(over)
    return MarketSample.model_validate(data)


def test_spread_median_and_quartiles() -> None:
    s = spread([550, 80, 200, 90])
    assert s is not None
    assert (s.n, s.min, s.median, s.max) == (4, 80, 145, 550)
    assert s.q1 == 87.5 and s.q3 == 287.5
    one = spread([100])
    assert one is not None and one.q1 == one.median == one.q3 == 100
    assert spread([]) is None


def test_item_spread_by_key() -> None:
    sample = _sample()
    chase = item_spread(sample, "work.chase")
    assert chase is not None and chase.median == 145
    assert item_spread(sample, "work.cable") is None


def test_period_from_earliest_year_to_latest_month() -> None:
    sample = _sample()
    assert period(sample).as_dict() == {"start": "2024", "end": "2026-11", "dated": 3, "undated": 1}
    # Only the used sources; a year without a month does not hide a known month at the end
    assert period(sample, {"b", "c"}).as_dict() == {
        "start": "2026-03",
        "end": "2026-11",
        "dated": 2,
        "undated": 0,
    }
    assert period(sample, {"d"}).as_dict() == {"start": "", "end": "", "dated": 0, "undated": 1}
    assert used_sources(sample) == {"a", "b", "c", "d"}


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"items": {"work.nope": {"quotes": {}}}}, "нет такой позиции сметы"),
        (
            {"items": {"work.chase": {"quotes": {"x": {"price": 1, "text": "t"}}}}},
            "нет такого источника",
        ),
        ({"sources": {"a": {"name": "A", "url": "u", "date": "март 2026"}}}, "ГГГГ"),
    ],
)
def test_sample_errors(over: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _sample(**over)


def test_real_sample_reads() -> None:
    data = yaml.safe_load((ROOT / "projects" / "market.yaml").read_text("utf-8"))
    sample = MarketSample.model_validate(data)
    assert all(key.startswith("work.") for key in sample.items)
    assert used_sources(sample) <= set(sample.sources)
