"""Карточки объектов проекта для подсказок в просмотре: заголовок и строки «что — значение».

Ключ — тот же «тип:id», что в XDATA примитивов (ids.py) и в ключе `o` артефакта .epd.
Всё — из модели и расчёта проводки (wiring.py), на языке проекта; в DXF не пишется.
Линия проводки называется по смыслу — «QF4: К3 → Розетка, Кухня», а не по wire_n.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from floorplan_engine.draw_plan import room_geometries
from floorplan_engine.draw_wiring import lay_out
from floorplan_engine.elevations import behind_text, wall_elevations
from floorplan_engine.geometry import Contour, Vec
from floorplan_engine.panel import BoardPanel, amps, build_panel, kw
from floorplan_engine.schema import Electrical, ElectricalPoint, OpeningType, Plan
from floorplan_engine.symbols import symbol_key
from floorplan_engine.texts import Language, tr
from floorplan_engine.wiring import (
    BOX_ABOVE_FLOOR,
    BOX_BELOW_CEILING,
    BOX_CLEARANCE,
    BOX_TITLES,
    RESERVE,
    Run,
    Wiring,
    box_wall,
)

TEXT: dict[str, dict[str, str]] = {
    "group": {"ru": "Автомат (группа)", "uk": "Автомат (група)"},
    "cable": {"ru": "Кабель", "uk": "Кабель"},
    "assumed": {"ru": "{mark} — допущение", "uk": "{mark} — припущення"},
    "from": {"ru": "Откуда", "uk": "Звідки"},
    "to": {"ru": "Куда", "uk": "Куди"},
    "route": {"ru": "Трасса", "uk": "Траса"},
    "ceiling": {"ru": "по потолку", "uk": "по стелі"},
    "floor": {"ru": "по полу, в стяжке", "uk": "по підлозі, у стяжці"},
    "length": {"ru": "Длина", "uk": "Довжина"},
    "parts": {
        "ru": "{total} м: по плану {plan}, вертикаль {vert}, выпуски {ends}",
        "uk": "{total} м: по плану {plan}, вертикаль {vert}, випуски {ends}",
    },
    "with_reserve": {"ru": "С запасом {pct} %", "uk": "З запасом {pct} %"},
    "box": {"ru": "Коробка {label}", "uk": "Коробка {label}"},
    "box_where": {"ru": "коробка {label}, {room}", "uk": "коробка {label}, {room}"},
    "room": {"ru": "Помещение", "uk": "Приміщення"},
    "lines": {"ru": "Линий", "uk": "Ліній"},
    "box_lines": {"ru": "{n}: 1 от щита, {k} к точкам", "uk": "{n}: 1 від щита, {k} до точок"},
    "box_height": {"ru": "Высота", "uk": "Висота"},
    "box_size": {"ru": "Типоразмер", "uk": "Типорозмір"},
    "below_ceiling": {"ru": "{mm} мм ниже потолка", "uk": "{mm} мм нижче стелі"},
    "on_ceiling": {
        "ru": "на потолке, к центру помещения",
        "uk": "на стелі, ближче до центру приміщення",
    },
    "above_floor": {"ru": "{mm} мм от пола", "uk": "{mm} мм від підлоги"},
    "wet": {"ru": "Влажное помещение", "uk": "Вологе приміщення"},
    "ip44": {"ru": "коробка IP44", "uk": "коробка IP44"},
    "wall": {"ru": "Стена", "uk": "Стіна"},
    "offset": {"ru": "От начала стены", "uk": "Від початку стіни"},
    "height": {"ru": "Высота", "uk": "Висота"},
    "ceiling_point": {"ru": "на потолке", "uk": "на стелі"},
    "posts": {"ru": "Постов", "uk": "Постів"},
    "note": {"ru": "Примечание", "uk": "Примітка"},
    "feed": {"ru": "Питание", "uk": "Живлення"},
    "from_board": {"ru": "от щита {board}", "uk": "від щита {board}"},
    "no_group": {
        "ru": "группы нет — в расчёт проводки не входит",
        "uk": "групи немає — до розрахунку проводки не входить",
    },
    "groups": {"ru": "Автоматы", "uk": "Автомати"},
    "board_lines": {"ru": "Линий от щита", "uk": "Ліній від щита"},
    "area": {"ru": "Площадь", "uk": "Площа"},
    "ceiling_height": {"ru": "Высота потолка", "uk": "Висота стелі"},
    "default": {"ru": "{h} мм (допущение)", "uk": "{h} мм (припущення)"},
    "thickness": {"ru": "Толщина", "uk": "Товщина"},
    "kind": {"ru": "Тип", "uk": "Тип"},
    "bearing": {"ru": "несущая", "uk": "несуча"},
    "partition": {"ru": "перегородка", "uk": "перегородка"},
    "width": {"ru": "Ширина", "uk": "Ширина"},
    "sill": {"ru": "Подоконник", "uk": "Підвіконня"},
    "door": {"ru": "Дверь", "uk": "Двері"},
    "window": {"ru": "Окно", "uk": "Вікно"},
    "opening": {"ru": "Проём", "uk": "Проріз"},
    "dimension": {"ru": "Размеры стены {wall}", "uk": "Розміри стіни {wall}"},
    "points": {"ru": "Точки", "uk": "Точки"},
    "label": {"ru": "Подпись точек", "uk": "Підпис точок"},
    "led": {"ru": "LED-подсветка", "uk": "LED-підсвітка"},
    "board": {"ru": "Щит {name}", "uk": "Щит {name}"},
    "device": {"ru": "Аппарат", "uk": "Апарат"},
    "load": {"ru": "Нагрузка", "uk": "Навантаження"},
    "load_value": {"ru": "{p} кВт, {i} А", "uk": "{p} кВт, {i} А"},
    "load_assumed": {
        "ru": "{p} кВт, {i} А (мощность типовая — допущение)",
        "uk": "{p} кВт, {i} А (потужність типова — припущення)",
    },
    "consumer": {"ru": "{title} ×{n}, {room}", "uk": "{title} ×{n}, {room}"},
    "consumer_one": {"ru": "{title}, {room}", "uk": "{title}, {room}"},
    "watts": {"ru": "{w} Вт", "uk": "{w} Вт"},
    "more": {"ru": "ещё {n}", "uk": "ще {n}"},
    "warning": {"ru": "Внимание", "uk": "Увага"},
    "behind": {"ru": "За стеной", "uk": "За стіною"},
    "points_on_wall": {"ru": "Точек", "uk": "Точок"},
}
CARD_LOADS = 8  # потребителей в карточке аппарата, остальные — «ещё N»


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


@dataclass(frozen=True)
class ObjectInfo:
    title: str
    rows: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {"title": self.title, "rows": [list(r) for r in self.rows]}


def _mm(value: float) -> str:
    return f"{value:g} мм"


def _m(mm: float) -> str:
    return f"{mm / 1000:.1f}".replace(".", ",")


def _point_name(pt: ElectricalPoint, language: Language) -> str:
    return tr(f"symbol_{symbol_key(pt)}", language)


def describe_objects(
    plan: Plan,
    contours: dict[str, Contour],
    elec: Electrical | None = None,
    wiring: Wiring | None = None,
) -> dict[str, ObjectInfo]:
    """Карточки всех объектов модели по ключу «тип:id»."""
    lang = plan.language
    out: dict[str, ObjectInfo] = {}
    height_assumed = "ceiling_height" not in plan.model_fields_set
    ceiling = (
        text("default", lang, h=f"{plan.ceiling_height:g}")
        if height_assumed
        else _mm(plan.ceiling_height)
    )
    for room in plan.rooms:
        contour = contours[room.id]
        rows = [
            (text("area", lang), f"{contour.area_m2:.2f} м²".replace(".", ",")),
            (text("ceiling_height", lang), ceiling),
        ]
        if room.wet:
            rows.append((text("wet", lang), text("ip44", lang)))
        out[f"room:{room.id}"] = ObjectInfo(room.name, tuple(rows))
        for seg in contour.segments:
            kind = text("bearing" if seg.bearing else "partition", lang)
            wall_rows = (
                (text("room", lang), room.name),
                (text("length", lang), _mm(seg.length)),
                (text("thickness", lang), _mm(seg.thickness)),
                (text("kind", lang), kind),
            )
            title = f"{text('wall', lang)} {seg.id}"
            out[f"wall:{room.id}.{seg.id}"] = ObjectInfo(title, wall_rows)
            out[f"dimension:{room.id}.{seg.id}"] = ObjectInfo(
                text("dimension", lang, wall=seg.id), wall_rows[:2]
            )
        for op in room.openings:
            name = {OpeningType.DOOR: "door", OpeningType.WINDOW: "window"}.get(op.type, "opening")
            rows = [
                (text("room", lang), room.name),
                (text("wall", lang), op.wall),
                (text("width", lang), _mm(op.width)),
            ]
            if op.height is not None:
                rows.append((text("height", lang), _mm(op.height)))
            if op.sill is not None:
                rows.append((text("sill", lang), _mm(op.sill)))
            out[f"opening:{op.id}"] = ObjectInfo(f"{text(name, lang)} {op.id}", tuple(rows))
    if elec is not None:
        out.update(_electrical(plan, elec, wiring))
        # Развёртки: имя (пейджер и подсказка просмотра) и что за стеной
        for e in wall_elevations(plan, contours, elec, wiring):
            out[f"elevation:{e.key}"] = ObjectInfo(
                tr("elev_card", lang, room=e.room_name, n=e.index),
                (
                    (text("length", lang), _mm(e.length)),
                    (text("behind", lang), behind_text(e, lang)),
                    (text("points_on_wall", lang), str(len(e.points))),
                ),
            )
        panel = build_panel(plan, elec)
        if panel is not None:
            out.update(device_cards(panel, lang))
    return out


def device_cards(panel: BoardPanel, lang: Language) -> dict[str, ObjectInfo]:
    """Карточки аппаратов листа «Щит»: у автомата группы — нагрузка, потребители и слабые
    места группы."""
    groups = {g.group: g for g in panel.groups}
    out: dict[str, ObjectInfo] = {}
    for d in panel.devices:
        g = groups.get(d.group or "")
        if g is None:
            out[d.key] = ObjectInfo(f"{d.id} — {d.title}", ((text("device", lang), d.label),))
            continue
        key = "load_assumed" if g.assumed else "load_value"
        rows = [
            (text("device", lang), d.label),
            (text("cable", lang), g.cable or "—"),
            (text("load", lang), text(key, lang, p=kw(g.power), i=amps(g.current))),
        ]
        for ld in g.loads[:CARD_LOADS]:
            k = "consumer" if ld.count > 1 else "consumer_one"
            label = text(k, lang, title=ld.title, n=ld.count, room=ld.room)
            rows.append((label, text("watts", lang, w=f"{ld.power:g}")))
        if len(g.loads) > CARD_LOADS:
            rows.append(("…", text("more", lang, n=len(g.loads) - CARD_LOADS)))
        rows += [
            (text("warning", lang), w.text[lang]) for w in panel.warnings if w.group == g.group
        ]
        out[d.key] = ObjectInfo(f"{d.id}: {g.purpose}", tuple(rows))
    return out


def _electrical(plan: Plan, elec: Electrical, wiring: Wiring | None) -> dict[str, ObjectInfo]:
    lang = plan.language
    rooms = {r.id: r.name for r in plan.rooms}
    points = {p.id: p for p in elec.points}
    board_name = elec.board.name if elec.board else "ЩР"
    boxes = {b.id: b for b in wiring.boxes} if wiring else {}
    feeds = {r.target: r for r in wiring.runs} if wiring else {}
    out: dict[str, ObjectInfo] = {}

    def where(end: str) -> str:
        if end == "board":
            return board_name
        if end in boxes:
            b = boxes[end]
            return text("box_where", lang, label=b.label, room=rooms.get(b.room, b.room))
        pt = points[end]
        return f"{_point_name(pt, lang)}, {rooms.get(pt.room, pt.room)}"

    def short(end: str) -> str:
        if end == "board":
            return board_name
        if end in boxes:
            return boxes[end].label
        pt = points[end]
        return f"{_point_name(pt, lang)}, {rooms.get(pt.room, pt.room)}"

    for pt in elec.points:
        rows = [(text("room", lang), rooms.get(pt.room, pt.room))]
        if pt.ceiling is None:
            rows += [
                (text("wall", lang), str(pt.wall)),
                (text("offset", lang), _mm(pt.offset or 0)),
                (text("height", lang), _mm(pt.height or 0)),
            ]
        else:
            rows.append((text("height", lang), text("ceiling_point", lang)))
        if pt.count > 1:
            rows.append((text("posts", lang), str(pt.count)))
        if pt.note:
            rows.append((text("note", lang), pt.note))
        run = feeds.get(pt.id)
        if pt.group is None:
            rows.append((text("group", lang), text("no_group", lang)))
        else:
            rows.append((text("group", lang), pt.group))
        if run is not None:
            src = (
                text("from_board", lang, board=board_name)
                if run.source == "board"
                else where(run.source)
            )
            rows += [
                (text("feed", lang), src),
                (text("length", lang), f"{_m(run.length_mm)} м"),
            ]
        out[f"point:{pt.id}"] = ObjectInfo(f"{_point_name(pt, lang)} · {pt.id}", tuple(rows))

    if wiring is not None:
        for run in wiring.runs:
            out[f"wire:{run.id}"] = _run_info(run, short, where, lang)
        for b in wiring.boxes:
            k = sum(1 for r in wiring.runs if r.source == b.id)
            if b.on_ceiling:
                height = text("on_ceiling", lang)
            elif b.route == "floor":
                height = text("above_floor", lang, mm=f"{BOX_ABOVE_FLOOR:g}")
            else:
                height = text("below_ceiling", lang, mm=f"{BOX_BELOW_CEILING:g}")
            rows = [
                (text("group", lang), b.group),
                (text("room", lang), rooms.get(b.room, b.room)),
                (text("lines", lang), text("box_lines", lang, n=k + 1, k=k)),
                (text("box_size", lang), BOX_TITLES.get(b.size, b.size)),
                (text("box_height", lang), height),
            ]
            if b.wet:
                rows.append((text("wet", lang), text("ip44", lang)))
            out[f"box:{b.id}"] = ObjectInfo(text("box", lang, label=b.label), tuple(rows))

    if elec.board is not None:
        groups = sorted({r.group for r in wiring.runs}) if wiring else []
        rows = [
            (text("room", lang), rooms.get(elec.board.room, elec.board.room)),
            (text("wall", lang), elec.board.wall),
            (text("height", lang), _mm(elec.board.height)),
        ]
        if wiring is not None:
            from_board = sum(1 for r in wiring.runs if r.source == "board")
            rows += [
                (text("groups", lang), ", ".join(groups)),
                (text("board_lines", lang), str(from_board)),
            ]
        out["board:board"] = ObjectInfo(text("board", lang, name=elec.board.name), tuple(rows))

    for strip in elec.led_strips:
        strip_rows = (
            (text("room", lang), rooms.get(strip.room, strip.room)),
            (text("wall", lang), strip.wall),
            (text("length", lang), _mm(strip.end - strip.start)),
        )
        out[f"led_strip:{strip.id}"] = ObjectInfo(f"{text('led', lang)} · {strip.id}", strip_rows)
    return out


def _run_info(
    run: Run, short: Callable[[str], str], where: Callable[[str], str], lang: Language
) -> ObjectInfo:
    route = text("floor" if run.route == "floor" else "ceiling", lang)
    mark = text("assumed", lang, mark=run.mark) if run.mark_assumed else run.mark
    parts = text(
        "parts",
        lang,
        total=_m(run.length_mm),
        plan=_m(run.plan_mm),
        vert=_m(run.vertical_mm),
        ends=_m(run.ends_mm),
    )
    rows = (
        (text("group", lang), run.group),
        (text("cable", lang), mark),
        (text("from", lang), where(run.source)),
        (text("to", lang), where(run.target)),
        (text("route", lang), route),
        (text("length", lang), parts),
        (
            text("with_reserve", lang, pct=round(RESERVE * 100)),
            f"{_m(run.length_mm * (1 + RESERVE))} м",
        ),
    )
    title = f"{run.group}: {short(run.source)} → {short(run.target)}"
    return ObjectInfo(title, rows)


def wire_titles(plan: Plan, elec: Electrical, wiring: Wiring) -> dict[str, str]:
    """Названия линий по смыслу для журнала: id линии → «QF4: К3 → Розетка…, Кухня»."""
    infos = _electrical(plan, elec, wiring)
    return {r.id: infos[f"wire:{r.id}"].title for r in wiring.runs}


def line_chains(wiring: Wiring) -> dict[str, list[str]]:
    """Что выделять по клику на листе проводки: объект → его линия целиком.
    Линия щит → коробка и сама коробка — с коробкой и всеми её линиями до точек;
    линия коробка → точка и точка — эта ветка, коробка и линия щит → коробка."""
    feed = {r.target: r for r in wiring.runs if r.source == "board"}
    children: dict[str, list[str]] = {}
    for r in wiring.runs:
        if r.source != "board":
            children.setdefault(r.source, []).extend([f"wire:{r.id}", f"point:{r.target}"])
    out: dict[str, list[str]] = {}

    def whole_box(box: str) -> list[str]:
        up = [f"wire:{feed[box].id}"] if box in feed else []
        return [*up, f"box:{box}", *children.get(box, [])]

    for b in wiring.boxes:
        out[f"box:{b.id}"] = whole_box(b.id)
    for r in wiring.runs:
        if r.target.startswith("box_"):
            chain = whole_box(r.target)
        else:
            chain = [f"wire:{r.id}"]
            if r.source != "board":
                chain.append(f"box:{r.source}")
                if r.source in feed:
                    chain.append(f"wire:{feed[r.source].id}")
            chain.append(f"point:{r.target}")
            out[f"point:{r.target}"] = chain
        out[f"wire:{r.id}"] = chain
    return out


def line_groups(wiring: Wiring) -> dict[str, list[str]]:
    """Состав каждой группы на листе проводки — для подсветки соседей выделенной линии:
    её линии, коробки и точки."""
    out: dict[str, list[str]] = {}
    for b in wiring.boxes:
        out.setdefault(b.group, []).append(f"box:{b.id}")
    for r in wiring.runs:
        keys = out.setdefault(r.group, [])
        keys.append(f"wire:{r.id}")
        if not r.target.startswith("box_"):
            keys.append(f"point:{r.target}")
    return out


def page_objects(
    keys: set[str], infos: dict[str, ObjectInfo], language: Language
) -> dict[str, dict[str, object]]:
    """Карточки объектов, нарисованных на странице. Общая подпись нескольких точек
    («label:a,b») — список их названий."""
    out: dict[str, dict[str, object]] = {}
    for key in sorted(keys):
        info = infos.get(key)
        if info is None and key.startswith("label:"):
            ids = key.removeprefix("label:").split(",")
            rows = tuple(
                (pid, infos[f"point:{pid}"].title) for pid in ids if f"point:{pid}" in infos
            )
            info = ObjectInfo(text("label", language), rows)
        if info is not None:
            out[key] = info.as_dict()
    return out


def _xy(v: Vec) -> list[float]:
    return [round(v.x, 1), round(v.y, 1)]


def wiring_handles(plan: Plan, contours: dict[str, Contour], wiring: Wiring) -> dict[str, Any]:
    """Что можно править на листе проводки (ключ `edit` страницы .epd), мм модели:
    трассы линий (от источника к цели) и как они нарисованы — со сдвигом в полосу пучка
    (lane, те же вершины; правится то, что видно на листе), и коробки — место, направление
    в помещение, сторона квадрата и отрезок стены, по которому коробку можно двигать (на
    потолке — нет). manual — правка из wiring.yaml применена. Потребители и щит не двигаются.
    Вызывать в масштабе листа (layers.drawing_scale): полосы — как на чертеже."""
    geoms = {g.room.id: g for g in room_geometries(plan, contours)}
    lanes, _ = lay_out(wiring)
    wires = {
        r.id: {
            "from": r.source,
            "to": r.target,
            "path": [_xy(v) for v in r.path],
            "lane": [_xy(v) for v in lane],
            "manual": f"wire:{r.id}" in wiring.edited,
        }
        for r, lane in zip(wiring.runs, lanes, strict=True)
    }
    boxes: dict[str, Any] = {}
    for b in wiring.boxes:
        a = b.anchor
        seg = box_wall(geoms[b.room], a)
        span = (
            [_xy(seg.point_at(BOX_CLEARANCE)), _xy(seg.point_at(seg.length - BOX_CLEARANCE))]
            if seg is not None and seg.length >= 2 * BOX_CLEARANCE
            else None
        )
        boxes[b.id] = {
            "room": b.room,
            "group": b.group,
            "label": b.label,
            "at": _xy(a.pos),
            "inward": None if a.inward is None else [round(a.inward.x, 6), round(a.inward.y, 6)],
            "size": round(a.depth, 1),
            "span": span,
            "manual": f"box:{b.id}" in wiring.edited,
        }
    return {"wires": wires, "boxes": boxes}
