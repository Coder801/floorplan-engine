"""Строки таблиц сантехники — на лист «Сантехника» и в боковую панель просмотра: приборы
(номер на листе, подводы, высоты; типовая высота — «*»), трубы по видам и диаметрам,
примечания (допущения и слабые места)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from floorplan_engine.electrical.elevations import WaterView
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.schema import Plan
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.network import (
    COLLECTOR_HEIGHT,
    SCREED_COVER,
    SCREED_MM,
    SLOPE,
    SLOPE_MIN,
    Kind,
    Network,
    fixture_name,
)

ASSUMED = "*"

TEXT: dict[str, dict[str, str]] = {
    "fixtures": {"ru": "Сантехприборы", "uk": "Сантехприлади"},
    "no": {"ru": "№", "uk": "№"},
    "fixture": {"ru": "Прибор", "uk": "Прилад"},
    "room": {"ru": "Помещение", "uk": "Приміщення"},
    "supply": {"ru": "Вода", "uk": "Вода"},
    "supply_h": {"ru": "Водорозетки, мм", "uk": "Водорозетки, мм"},
    "drain": {"ru": "Выпуск", "uk": "Випуск"},
    "drain_h": {"ru": "Выпуск, мм", "uk": "Випуск, мм"},
    "pipes": {"ru": "Трубы", "uk": "Труби"},
    "kind": {"ru": "Сеть", "uk": "Мережа"},
    "d": {"ru": "Ø, мм", "uk": "Ø, мм"},
    "count": {"ru": "Труб", "uk": "Труб"},
    "length": {"ru": "Длина, м", "uk": "Довжина, м"},
    "total": {"ru": "Всего", "uk": "Усього"},
    "cold": {"ru": "Холодная вода (В1)", "uk": "Холодна вода (В1)"},
    "hot": {"ru": "Горячая вода (Т3)", "uk": "Гаряча вода (Т3)"},
    "sewer": {"ru": "Канализация (К1)", "uk": "Каналізація (К1)"},
    "letter_cold": {"ru": "Х", "uk": "Х"},
    "letter_hot": {"ru": "Г", "uk": "Г"},
    "note_route": {
        "ru": "Трассы — по полу: вода в стяжке в теплоизоляции, горячая и холодная — парой; к "
        "прибору — в стене. {dist}",
        "uk": "Траси — по підлозі: вода в стяжці в теплоізоляції, гаряча і холодна — парою; до "
        "приладу — у стіні. {dist}",
    },
    "dist_collector": {
        "ru": "Разводка лучевая: у каждой водорозетки своя труба от коллектора.",
        "uk": "Розведення променеве: у кожної водорозетки своя труба від колектора.",
    },
    "dist_tee": {
        "ru": "Разводка тройниковая: магистраль Ø20, отводы Ø16.",
        "uk": "Розведення трійникове: магістраль Ø20, відводи Ø16.",
    },
    "note_holes": {
        "ru": "Сквозь перегородки — отверстием у пола, где обход через дверь длиннее: {n} шт.",
        "uk": "Крізь перегородки — отвором біля підлоги, де обхід через двері довший: {n} шт.",
    },
    "note_slope": {
        "ru": "Канализация: уклон к стояку {s} — один на всей трассе прибора (Ø110 — до {s110}, "
        "Ø50 — не меньше {s} по ДБН В.2.5-64); повороты — отводами 45°, врезка — косым "
        "тройником; через дверные проёмы и пороги жилых комнат — нет. От выпуска — вниз в "
        "стене, дальше по полу: в стяжке {h} мм (Ø50, слой над трубой {c} мм) или в коробе, "
        "инсталляции, под ванной; Ø110 — только скрыто, не в стяжке.",
        "uk": "Каналізація: ухил до стояка {s} — один на всій трасі приладу (Ø110 — до {s110}, "
        "Ø50 — не менше {s} за ДБН В.2.5-64); повороти — відводами 45°, врізка — косим "
        "трійником; через дверні прорізи й пороги житлових кімнат — ні. Від випуску — вниз у "
        "стіні, далі по підлозі: у стяжці {h} мм (Ø50, шар над трубою {c} мм) або в коробі, "
        "інсталяції, під ванною; Ø110 — лише приховано, не в стяжці.",
    },
    "note_assumed": {
        "ru": "* — высота не из проекта, типовая; уточнить по паспорту прибора.",
        "uk": "* — висота не з проєкту, типова; уточнити за паспортом приладу.",
    },
    "note_input": {
        "ru": "Узел ввода и коллекторы — у стояка, допущение; коллекторы на {h} мм от пола.",
        "uk": "Вузол вводу і колектори — біля стояка, припущення; колектори на {h} мм від підлоги.",
    },
    "note_inlet": {
        "ru": "Врезка в стояк {r} — ось на {h} мм от чистого пола, допущение.",
        "uk": "Врізка в стояк {r} — вісь на {h} мм від чистої підлоги, припущення.",
    },
    "note_hot_boiler": {
        "ru": "Горячая вода — от бойлера ({f}).",
        "uk": "Гаряча вода — від бойлера ({f}).",
    },
    "note_hot_riser": {
        "ru": "Горячая вода — из стояка (централизованная){a}.",
        "uk": "Гаряча вода — зі стояка (централізована){a}.",
    },
    "assumption": {"ru": ", допущение", "uk": ", припущення"},
    "weak": {"ru": "Слабые места:", "uk": "Слабкі місця:"},
}


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


@dataclass(frozen=True)
class FixtureRow:
    number: int
    id: str
    name: str
    room: str
    supply: str  # «Х, Г»
    supply_h: str  # «550*»
    drain: str  # «Ø50»
    drain_h: str

    @property
    def keys(self) -> tuple[str, ...]:
        return (f"fixture:{self.id}",)


def fixture_numbers(plumbing: Plumbing) -> dict[str, int]:
    """Номер прибора на листе — по порядку в plumbing.yaml."""
    return {f.id: k for k, f in enumerate(plumbing.fixtures, 1)}


def fixture_rows(plan: Plan, plumbing: Plumbing, net: Network) -> list[FixtureRow]:
    lang = plan.language
    rooms = {r.id: r.name for r in plan.rooms}
    numbers = fixture_numbers(plumbing)
    out = []
    for fx in plumbing.fixtures:
        outlets = net.by_fixture(fx.id)
        water = [o for o in outlets if o.kind in ("cold", "hot")]
        drain = next((o for o in outlets if o.kind == "sewer"), None)
        letters = [text(f"letter_{o.kind}", lang) for o in water]
        supply_h = ""
        if water:
            supply_h = f"{water[0].height:g}" + (ASSUMED if water[0].assumed else "")
        out.append(
            FixtureRow(
                numbers[fx.id],
                fx.id,
                fixture_name(fx, lang),
                rooms.get(fx.room, fx.room),
                ", ".join(letters),
                supply_h,
                f"Ø{drain.d}" if drain is not None else "",
                (f"{drain.height:g}" + (ASSUMED if drain.assumed else "")) if drain else "",
            )
        )
    return out


@dataclass(frozen=True)
class PipeRow:
    kind: Kind
    d: int
    count: int
    length: float  # мм, вся длина без запаса
    keys: tuple[str, ...]


def pipe_rows(net: Network) -> list[PipeRow]:
    groups: dict[tuple[Kind, int], list[str]] = defaultdict(list)
    lengths: dict[tuple[Kind, int], float] = defaultdict(float)
    for p in net.pipes:
        groups[(p.kind, p.d)].append(f"pipe:{p.id}")
        lengths[(p.kind, p.d)] += p.total
    order = {"cold": 0, "hot": 1, "sewer": 2}
    return [
        PipeRow(kind, d, len(keys), lengths[(kind, d)], tuple(keys))
        for (kind, d), keys in sorted(groups.items(), key=lambda kv: (order[kv[0][0]], kv[0][1]))
    ]


def plumbing_notes(plan: Plan, plumbing: Plumbing, net: Network) -> list[str]:
    """Примечания листа: трассы и разводка, уклоны, допущения, слабые места."""
    lang = plan.language
    dist = text(f"dist_{net.distribution}", lang)
    s, s110 = (f"{v:g}".replace(".", ",") for v in (SLOPE[50], SLOPE_MIN[110]))
    slope = text("note_slope", lang, s=s, s110=s110, h=f"{SCREED_MM:g}", c=f"{SCREED_COVER:g}")
    out = [text("note_route", lang, dist=dist), slope]
    holes = net.holes(("cold", "hot")) + net.holes(("sewer",))
    if holes:
        out.append(text("note_holes", lang, n=holes))
    if net.input_assumed:
        out.append(text("note_input", lang, h=f"{COLLECTOR_HEIGHT:g}"))
    for r in net.risers:
        if r.sewer and r.inlet_assumed:
            out.append(text("note_inlet", lang, r=r.id, h=f"{r.inlet:g}"))
    if net.hot_source == "riser":
        given = plumbing.input is not None and plumbing.input.hot is not None
        out.append(text("note_hot_riser", lang, a="" if given else text("assumption", lang)))
    elif net.hot_source is not None:
        fx = next(f for f in plumbing.fixtures if f.id == net.hot_source)
        out.append(text("note_hot_boiler", lang, f=fixture_name(fx, lang)))
    if any(o.assumed for o in net.outlets):
        out.append(text("note_assumed", lang))
    if net.weak:
        out.append(text("weak", lang))
        out += [f"— {w.text[lang]}" for w in net.weak]
    return out


def water_views(plumbing: Plumbing, net: Network) -> dict[tuple[str, str], list[WaterView]]:
    """Подводы приборов по стенам — на развёртки (electrical/elevations.wall_elevations)."""
    numbers = fixture_numbers(plumbing)
    langs: tuple[Language, ...] = ("ru", "uk")
    names: dict[str, dict[str, str]] = {
        f.id: {lang: fixture_name(f, lang) for lang in langs} for f in plumbing.fixtures
    }
    out: dict[tuple[str, str], list[WaterView]] = defaultdict(list)
    for o in net.outlets:
        out[(o.room, o.wall)].append(
            WaterView(
                o.fixture,
                numbers[o.fixture],
                o.kind,
                o.offset,
                o.height,
                o.d,
                o.assumed,
                names.get(o.fixture, {}),
            )
        )
    return dict(out)
