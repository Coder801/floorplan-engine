"""Спецификация изделий электрики: количество по модели."""

from __future__ import annotations

from floorplan_engine.schema import Electrical
from floorplan_engine.specification import specification, specification_table


def _elec() -> Electrical:
    wall = {"room": "r", "wall": "w1", "offset": 500, "height": 300}
    return Electrical.model_validate(
        {
            "points": [
                {"id": "s1", "type": "socket", "count": 2, **wall},
                {"id": "s2", "type": "socket", **wall},
                {"id": "k1", "type": "switch", "keys": 2, **wall},
                {"id": "k2", "type": "switch", **wall},
                {"id": "d1", "type": "data", **wall},
                {"id": "l1", "type": "downlight", "room": "r", "ceiling": [1000, 1000]},
                {"id": "l2", "type": "downlight", "room": "r", "ceiling": [2000, 1000]},
                {"id": "b1", "type": "sconce", **wall},
            ],
            "led_strips": [{"id": "led1", "room": "r", "wall": "w2", "start": 0, "end": 1450}],
            "board": {"room": "r", "wall": "w3", "offset": 200, "height": 1700},
        }
    )


def test_quantities() -> None:
    items = {i.name: (i.quantity, i.unit) for i in specification(_elec())}
    assert items == {
        "Розетка с заземлением": (3, "pcs"),
        "Выключатель одноклавишный": (1, "pcs"),
        "Выключатель двухклавишный": (1, "pcs"),
        "Розетка интернет": (1, "pcs"),
        "Подрозетник": (6, "pcs"),  # 2 + 1 розетки, 2 выключателя, интернет; бра — без
        "Рамка 1-постовая": (4, "pcs"),
        "Рамка 2-постовая": (1, "pcs"),
        "Светильник точечный": (2, "pcs"),
        "Бра": (1, "pcs"),
        "LED-подсветка": (1.45, "m"),
        "Щит распределительный": (1, "pcs"),
    }


def test_table_in_ukrainian() -> None:
    table = specification_table(_elec(), "uk")
    assert table is not None and table.title == "Специфікація виробів"
    assert ("10", "LED-підсвітка", "м", "1,45") in table.rows


def test_no_items_no_table() -> None:
    assert specification_table(Electrical(), "ru") is None
