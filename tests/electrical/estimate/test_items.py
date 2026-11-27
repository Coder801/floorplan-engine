"""Electrical estimate items: keys with a parameter, cable names."""

from __future__ import annotations

import pytest

from floorplan_engine.electrical.estimate.items import (
    cable_title,
    split_key,
)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("cable.3x1.5", ("cable", "3x1.5")),
        ("frame.2", ("frame", "2")),
        ("cable", ("cable", "")),
        ("cable.", ("cable.", "")),
        ("work.cable", ("work.cable", "")),
        ("socket", ("socket", "")),
        ("", ("", "")),
    ],
)
def test_split_key(key: str, expected: tuple[str, str]) -> None:
    assert split_key(key) == expected


@pytest.mark.parametrize(
    ("mark", "title"),
    [
        ("3x6", "ВВГнг 3×6"),
        ("3x2.5", "ВВГнг 3×2,5"),
        ("5х2,5", "ВВГнг 5×2,5"),
        ("ВВГнг-LS 3x2.5", "ВВГнг-LS 3x2.5"),
        ("UTP cat.6", "UTP cat.6"),
        ("RG-6", "RG-6"),
    ],
)
def test_cable_title_adds_the_brand_to_a_bare_section(mark: str, title: str) -> None:
    assert cable_title(mark) == title


def test_split_key_with_work_parameter() -> None:
    assert split_key("work.chase.brick") == ("work.chase", "brick")
    assert split_key("work.chase_wide.concrete") == ("work.chase_wide", "concrete")
    assert split_key("work.chase") == ("work.chase", "")
    assert split_key("work.cable") == ("work.cable", "")
    assert split_key("cable.3x1.5") == ("cable", "3x1.5")
