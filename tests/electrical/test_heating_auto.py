from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from floorplan_engine.electrical.heating_auto import (
    NONE,
    Place,
    auto_heating,
    note_area,
    note_places,
    parse_place,
)
from floorplan_engine.model.schema import Electrical, Plan, Room
from floorplan_engine.validation.validate import validate_project
from tests.conftest import make_flat


def _zoned() -> Plan:
    """The test flat with the kitchen split in two zones."""
    flat = make_flat()
    kitchen = Room.model_validate(
        flat.rooms[1].model_dump()
        | {
            "name": "Кухня-вітальня + передпокій",
            "zones": [
                {"name": "Передпокій", "walls": ["w1", "w2"]},
                {"name": "Кухня-вітальня", "walls": ["w3", "w4"]},
            ],
        }
    )
    return flat.model_copy(update={"rooms": [flat.rooms[0], kitchen]})


def _reg(rid: str = "t1", room: str = "kitchen", note: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"id": rid, "room": room, "type": "thermostat", "wall": "w2"}
    out |= {"offset": 500, "height": 900}
    return out | ({"note": note} if note else {})


def _elec(*points: dict[str, Any], **extra: Any) -> Electrical:
    return Electrical.model_validate({"points": list(points)} | extra)


def test_note_names_a_room_or_zone() -> None:
    flat, zoned = make_flat(), _zoned()
    assert note_places(flat, "терморегулятор, тепла підлога, санвузол") == []  # «санву…»
    assert note_places(flat, "ТП санузел, зона 1,7 м²") == [Place("bath")]
    assert note_places(flat, "тёплый пол в кухне") == [Place("kitchen")]
    assert note_places(flat, "терморегулятор") == []
    # A zone beats its own room; Ukrainian forms fit by the prefix
    assert note_places(zoned, "тепла підлога, кухня") == [Place("kitchen", "Кухня-вітальня")]
    assert note_places(zoned, "у передпокої") == [Place("kitchen", "Передпокій")]
    # Both zones named: the room's own name has both words, so the whole room
    assert note_places(zoned, "кухня і передпокій") == [Place("kitchen")]
    assert note_places(flat, "санузел и кухня") == [Place("bath"), Place("kitchen")]
    assert note_area("тепла підлога, зона 6,35 м²") == 6.35
    assert note_area("тп 4 м2") == 4.0 and note_area("тп") is None


def test_zone_by_note_else_the_controllers_room() -> None:
    flat = make_flat()
    elec = _elec(_reg("t1", note="тёплый пол санузел, 2,1 м²"), _reg("t2"))
    found = auto_heating(flat, elec)
    assert found.questions == ()
    a, b = found.zones
    assert (a.id, a.room, a.zone, a.thermostat, a.area, a.auto) == (
        "auto_t1",
        "bath",
        None,
        "t1",
        2.1,
        True,
    )
    assert (b.room, b.thermostat, b.area) == ("kitchen", "t2", None)
    # A controller that a written zone names gets nothing
    named = _elec(_reg("t1"), floor_heating=[{"id": "fh", "room": "bath", "thermostat": "t1"}])
    assert auto_heating(flat, named).zones == ()


# Words of the question texts by language: several places, several zones, the whole room named,
# the floor taken, "no floor heating"
WORDS = {
    "ru": ("нескольким", "несколько зон", "помещение целиком", "уже греет", "Без тёплого пола"),
    "uk": ("кількох", "кілька зон", "приміщення цілком", "вже гріє", "Без теплої підлоги"),
}


@pytest.mark.parametrize("lang", ["ru", "uk"])
def test_questions_when_code_cannot_tell(lang: str) -> None:
    many_w, zones_w, named_w, taken_w, none_w = WORDS[lang]
    flat = make_flat().model_copy(update={"language": lang})
    zoned = _zoned().model_copy(update={"language": lang})
    many = auto_heating(flat, _elec(_reg(note="санузел и кухня")))
    (q,) = many.questions
    assert many.zones == () and q.id == "heating_t1" and q.target == "heating_rooms.t1"
    assert q.options == ["bath", "kitchen", NONE]
    assert q.option_labels == {"bath": "Санузел", "kitchen": "Кухня", NONE: none_w}
    assert q.assumption == NONE and q.audience == "studio" and many_w in q.text
    (zones_q,) = auto_heating(zoned, _elec(_reg())).questions
    assert zones_w in zones_q.text
    assert zones_q.options == ["kitchen:Передпокій", "kitchen:Кухня-вітальня", NONE]
    assert zones_q.option_labels["kitchen:Передпокій"].endswith("— Передпокій")
    # The floor is already heated by a written zone
    taken = _elec(
        _reg("t1", room="bath"),
        _reg("t2", note="санузел"),
        floor_heating=[{"id": "fh", "room": "bath", "thermostat": "t1"}],
    )
    (tq,) = auto_heating(flat, taken).questions
    assert tq.id == "heating_t2" and "fh" in tq.text and taken_w in tq.text
    assert tq.options == ["kitchen", NONE]  # the heated floor is not offered again
    # The note names a room that has zones (its name wins over theirs), but none of the zones:
    # a question, not a zone over the whole room
    whole = auto_heating(
        zoned, _elec(_reg("t1", room="bath", note="ТП кухня-вітальня, передпокій"))
    )
    (nq,) = whole.questions
    assert whole.zones == () and named_w in nq.text
    assert nq.options == ["kitchen:Передпокій", "kitchen:Кухня-вітальня", NONE]


def test_heating_rooms_decides() -> None:
    zoned = _zoned()
    chosen = _elec(_reg(), heating_rooms={"t1": "kitchen:Передпокій"})
    found = auto_heating(zoned, chosen)
    assert found.questions == ()
    (z,) = found.zones
    assert (z.room, z.zone) == ("kitchen", "Передпокій")
    off = _elec(_reg(), heating_rooms={"t1": NONE})
    assert auto_heating(zoned, off) == auto_heating(zoned, _elec())
    assert parse_place(zoned, "kitchen:нет") is None and parse_place(zoned, "x") is None


@pytest.mark.parametrize("answer", ["kitchen", "none"])
def test_answer_in_answers_yaml_builds_the_zone(tmp_path: Path, answer: str) -> None:
    flat = make_flat()
    (tmp_path / "room.yaml").write_text(
        yaml.safe_dump(flat.model_dump(mode="json", exclude_defaults=True), allow_unicode=True),
        "utf-8",
    )
    elec = {
        "points": [_reg("t1", room="bath"), _reg("t2", note="санузел")],
        "floor_heating": [{"id": "fh", "room": "bath", "thermostat": "t1"}],
    }
    (tmp_path / "electrical.yaml").write_text(yaml.safe_dump(elec, allow_unicode=True), "utf-8")
    before = validate_project(tmp_path)
    assert before.ok and [q.id for q in before.auto_questions if q.id.startswith("heating_")] == [
        "heating_t2"
    ]
    assert before.question_states["heating_t2"] == "open"
    (tmp_path / "answers.yaml").write_text(f"answers:\n  heating_t2: {answer}\n", "utf-8")
    after = validate_project(tmp_path)
    assert after.ok and after.question_states["heating_t2"] == "answered"
    assert after.electrical is not None
    auto = [fh for fh in after.electrical.floor_heating if fh.auto]
    assert [fh.room for fh in auto] == ([] if answer == "none" else ["kitchen"])
    (tmp_path / "answers.yaml").write_text("answers:\n  heating_t2: garage\n", "utf-8")
    errors = validate_project(tmp_path).errors
    assert [(e.file, e.path) for e in errors] == [("answers.yaml", "answers.heating_t2")]
