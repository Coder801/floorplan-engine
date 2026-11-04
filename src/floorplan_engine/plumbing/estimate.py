"""Plumbing estimate: quantities come from the network (network.py), prices from the studio or
project price list on top of the price service, as for electrical (electrical/pricing.py).
Rows are the same `Line` and `Estimate`, so the files (md, csv, xlsx with formulas) and the
sheet table are shared with electrical.

- water: the REHAU RAUTITAN system (BRAND), pipes and fittings by diameter (16 and 20):
  pipes are the full length (on the floor, in the wall along and up to the water outlet)
  with a RESERVE margin; insulation on floor pipes (in the screed); a water outlet (wall
  elbow) for each fixture supply; a 90° elbow at each plan route turn and at the bottom of
  each vertical piece in a wall (at a fixture, manifold, boiler); a tee for each branch
  (tee layout: 20-16-20, 16-16-16, 20-20-20 by main and branch diameter); an adapter at the
  pipe end at a manifold (eurocone, radial) and at the supply unit or boiler (male thread);
  a sleeve at each pipe end in a fitting (`water_fittings`); manifolds by outlets;
- supply unit: for each water feed from a riser a valve, a filter, a reducer; meters only if
  plumbing.yaml has meters: true; a safety group at the boiler;
- sewer by diameter with a margin; 45° bends: a 90° turn always takes two, along the route
  (network_model.Pipe.bends) and on the drop from the drain in the wall (network_model.drop_bends:
  down and onto the floor is four, a short offset two); an angled tee for each branch into a pipe
  (by the diameter of the pipe branched into; Ø50 into Ø110 is 110×50); a riser inlet for
  each pipe entering the riser; a 110→50 reducer for each Ø50 entering the riser; a cleanout
  on a pipe with more than SEWER_BENDS bends;
- fixings at FIXING_STEP along floor pipes;
- holes in partitions: neighbouring pipes share one (network_model.Network.holes), water and
  sewer use separate ones;
- sewer in a chase: down the wall from the drain to the floor pipe (rise) and along the
  walls on the floor (plan length in the screed); what does not fit in the screed runs along
  the wall above the floor, in a box by the wall (network_model.Pipe.surface_length);
- work: laying by length without margin, water outlets, supply unit, tees, chases for rises
  to water outlets and drains (one chase for water and one for the drain per fixture),
  system pressure test. All of it is rough work (`rough`, before screed and tiles): water
  outlets go into the wall before finishing; the estimate has no finishing work, fixtures
  and mixers are not included.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from floorplan_engine.electrical.estimate import SECTIONS, Estimate, Line, PriceSource, Section
from floorplan_engine.model.plumbing import Plumbing
from floorplan_engine.model.texts import Language
from floorplan_engine.plumbing.bends import simplify, turn
from floorplan_engine.plumbing.network_model import Network, Pipe, drop_bends
from floorplan_engine.plumbing.rules import SEWER_BENDS

RESERVE = 0.1  # pipe margin
FIXING_STEP = 500.0  # mm: pipe fixing step on the floor
DRAIN_CHASE_MIN = 150.0  # mm: a lower drain gets no chase, it goes straight to the floor
BRAND = "REHAU RAUTITAN"  # water system: pipes and press fittings with a sliding sleeve
DIAMETERS = (16, 20)  # mm: branches 16, main and boiler feed 20


Unit = str | dict[Language, str]  # one unit for both languages ("шт", "м") or per language


def _water(key: str, unit: Unit, ru: str, uk: str) -> dict[str, tuple[Section, Unit, str, str]]:
    """A water item for each diameter: water.<key>16, water.<key>20."""
    return {
        f"water.{key}{d}": ("material", unit, ru.format(b=BRAND, d=d), uk.format(b=BRAND, d=d))
        for d in DIAMETERS
    }


def unit_text(unit: Unit, language: Language) -> str:
    return unit if isinstance(unit, str) else unit[language]


# Estimate items: key → section, unit, name (ru, uk)
LINES: dict[str, tuple[Section, Unit, str, str]] = {
    **_water("pipe", "м", "Труба {b} flex {d}", "Труба {b} flex {d}"),
    "water.insulation": (
        "material",
        "м",
        "Теплоизоляция трубы в стяжке",
        "Теплоізоляція труби в стяжці",
    ),
    **_water("outlet", "шт", "Водорозетка {b} {d}-Rp½", "Водорозетка {b} {d}-Rp½"),
    **_water("elbow", "шт", "Угольник 90° {b} PX {d}", "Кутник 90° {b} PX {d}"),
    "water.tee16": (
        "material",
        "шт",
        f"Тройник {BRAND} PX 16-16-16",
        f"Трійник {BRAND} PX 16-16-16",
    ),
    "water.tee20_16": (
        "material",
        "шт",
        f"Тройник {BRAND} PX 20-16-20",
        f"Трійник {BRAND} PX 20-16-20",
    ),
    "water.tee20": (
        "material",
        "шт",
        f"Тройник {BRAND} PX 20-20-20",
        f"Трійник {BRAND} PX 20-20-20",
    ),
    **_water(
        "eurocone", "шт", "Переходник {b} {d}-G¾ евроконус", "Перехідник {b} {d}-G¾ євроконус"
    ),
    **_water(
        "adapter",
        "шт",
        "Переходник {b} {d}-R½ наружная резьба",
        "Перехідник {b} {d}-R½ зовнішня різьба",
    ),
    **_water("sleeve", "шт", "Гильза монтажная {b} {d}", "Гільза монтажна {b} {d}"),
    "water.collector": (
        "material",
        {"ru": "вых.", "uk": "вих."},
        "Коллектор с кранами (за выход)",
        "Колектор із кранами (за вихід)",
    ),
    "water.valve": ("material", "шт", "Кран шаровой на вводе", "Кран кульовий на вводі"),
    "water.filter": ("material", "шт", "Фильтр грубой очистки", "Фільтр грубого очищення"),
    "water.reducer": ("material", "шт", "Редуктор давления", "Редуктор тиску"),
    "water.meter": ("material", "шт", "Счётчик воды", "Лічильник води"),
    "water.boiler_kit": (
        "material",
        "шт",
        "Группа безопасности бойлера",
        "Група безпеки бойлера",
    ),
    "water.fixing": ("material", "шт", "Крепление трубы", "Кріплення труби"),
    "sewer.pipe50": ("material", "м", "Труба канализационная Ø50", "Труба каналізаційна Ø50"),
    "sewer.pipe110": ("material", "м", "Труба канализационная Ø110", "Труба каналізаційна Ø110"),
    "sewer.bend50": ("material", "шт", "Отвод 45° Ø50", "Відвід 45° Ø50"),
    "sewer.bend110": ("material", "шт", "Отвод 45° Ø110", "Відвід 45° Ø110"),
    "sewer.tee50": ("material", "шт", "Тройник косой Ø50", "Трійник косий Ø50"),
    "sewer.tee110": ("material", "шт", "Тройник косой Ø110", "Трійник косий Ø110"),
    "sewer.tee110_50": ("material", "шт", "Тройник косой 110×50", "Трійник косий 110×50"),
    "sewer.riser_tee": (
        "material",
        "шт",
        "Тройник врезки в стояк Ø110",
        "Трійник врізки в стояк Ø110",
    ),
    "sewer.reducer": ("material", "шт", "Переход 110→50", "Перехід 110→50"),
    "sewer.revision": ("material", "шт", "Ревизия", "Ревізія"),
    "sewer.fixing": ("material", "шт", "Хомут канализации", "Хомут каналізації"),
    "work.water_pipe": (
        "rough",
        "м",
        "Прокладка трубы водоснабжения",
        "Прокладання труби водопостачання",
    ),
    "work.sewer_pipe": ("rough", "м", "Прокладка канализации", "Прокладання каналізації"),
    "work.water_outlet": ("rough", "шт", "Установка водорозетки", "Встановлення водорозетки"),
    "work.input": (
        "rough",
        "шт",
        "Монтаж узла ввода и коллекторов",
        "Монтаж вузла вводу і колекторів",
    ),
    "work.riser_tee": ("rough", "шт", "Врезка в стояк", "Врізка в стояк"),
    "work.wall_hole": (
        "rough",
        "шт",
        "Отверстие в перегородке под трубы",
        "Отвір у перегородці під труби",
    ),
    "work.chase_pipe": ("rough", "м", "Штроба под трубы воды", "Штроба під труби води"),
    "work.chase_sewer": ("rough", "м", "Штроба под канализацию", "Штроба під каналізацію"),
    "work.chase_sewer_floor": (
        "rough",
        "м",
        "Штроба в полу под канализацию",
        "Штроба в підлозі під каналізацію",
    ),
    "work.sewer_box": (
        "rough",
        "м",
        "Короб под канализацию у стены",
        "Короб під каналізацію біля стіни",
    ),
    "work.pressure_test": (
        "rough",
        "шт",
        "Опрессовка водоснабжения",
        "Опресування водопостачання",
    ),
}
# Price service mock (electrical/pricing.MockPriceService, extra): UAH per unit, a rough
# Kyiv guide for autumn 2026, not market prices
MOCK_PRICES: dict[str, float] = {
    "water.pipe16": 75,
    "water.pipe20": 115,
    "water.outlet16": 260,
    "water.outlet20": 330,
    "water.elbow16": 190,
    "water.elbow20": 260,
    "water.sleeve16": 45,
    "water.sleeve20": 60,
    "water.eurocone16": 170,
    "water.eurocone20": 230,
    "water.adapter16": 210,
    "water.adapter20": 280,
    "water.tee16": 270,
    "water.tee20_16": 330,
    "water.tee20": 360,
    "water.insulation": 15,
    "water.collector": 350,
    "water.valve": 350,
    "water.filter": 450,
    "water.reducer": 1500,
    "water.meter": 900,
    "water.boiler_kit": 900,
    "water.fixing": 6,
    "sewer.pipe50": 70,
    "sewer.pipe110": 170,
    "sewer.bend50": 35,
    "sewer.bend110": 70,
    "sewer.tee50": 50,
    "sewer.tee110": 110,
    "sewer.tee110_50": 90,
    "sewer.riser_tee": 600,
    "sewer.reducer": 40,
    "sewer.revision": 150,
    "sewer.fixing": 15,
    "work.water_pipe": 120,
    "work.sewer_pipe": 200,
    "work.water_outlet": 350,
    "work.input": 2500,
    "work.riser_tee": 1200,
    "work.wall_hole": 250,
    "work.chase_pipe": 350,
    "work.chase_sewer": 600,
    "work.chase_sewer_floor": 500,
    "work.sewer_box": 450,
    "work.pressure_test": 1000,
}
TEXT: dict[str, dict[str, str]] = {
    "title": {"ru": "Смета сантехники: {name}", "uk": "Кошторис сантехніки: {name}"},
    "sheet_title": {"ru": "Смета сантехники", "uk": "Кошторис сантехніки"},
    "sheet_volumes": {"ru": "Ведомость объёмов сантехники", "uk": "Відомість обсягів сантехніки"},
    "note_pipes": {
        "ru": "Трубы — с запасом {pct} %; прокладка — по фактической длине; трассы по полу",
        "uk": "Труби — із запасом {pct} %; прокладання — за фактичною довжиною; траси по підлозі",
    },
    "note_input": {
        "ru": "Узел ввода: кран, фильтр и редуктор на каждую воду из стояка; счётчики — "
        "только если указаны",
        "uk": "Вузол вводу: кран, фільтр і редуктор на кожну воду зі стояка; лічильники — "
        "лише якщо вказані",
    },
    "note_excluded": {
        "ru": "Не входит: сантехприборы, смесители, инсталляция, сифоны, отопление",
        "uk": "Не входить: сантехприлади, змішувачі, інсталяція, сифони, опалення",
    },
    "note_questions": {
        "ru": "Открытые вопросы по сантехнике: {ids} — объёмы могут измениться",
        "uk": "Відкриті питання з сантехніки: {ids} — обсяги можуть змінитися",
    },
}


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


def _d(p: Pipe) -> int:
    return 20 if p.d >= 20 else 16


def elbows(p: Pipe) -> int:
    """90° elbows on a water pipe: each plan route turn (including the tail along the wall) and the
    bottom of each vertical piece in a wall at the pipe end on the wall (fixture, manifold,
    boiler); a branch starts with a tee in the screed and has no vertical."""
    pts = simplify(p.path)
    plan = sum(
        round(turn(b - a, c - b) / 90) for a, b, c in zip(pts, pts[1:], pts[2:], strict=False)
    )
    return plan + (1 if p.parent is not None else 2)


def water_fittings(net: Network) -> dict[str, int]:
    """REHAU water fittings by LINES keys: water outlets, elbows, tees, adapters and sleeves, one
    sleeve per pipe end in a fitting."""
    q: defaultdict[str, int] = defaultdict(int)
    water = [p for p in net.pipes if p.kind in ("cold", "hot")]
    by_id = {p.id: p for p in water}
    fixtures = {o.fixture for o in net.outlets}
    for p in water:
        d = _d(p)
        n = elbows(p)
        q[f"water.elbow{d}"] += n
        q[f"water.sleeve{d}"] += 2 + 2 * n  # both ends and both sides of every elbow
        ends = [p.target] if p.parent is not None else [p.source, p.target]
        for end in ends:
            if end in fixtures:
                q[f"water.outlet{d}"] += 1  # also at the boiler: inlet and outlet are water outlets
            elif end == p.source and net.distribution == "collector":
                q[f"water.eurocone{d}"] += 1  # manifold outlet
            else:
                q[f"water.adapter{d}"] += 1  # supply unit (tee layout), manifold inlet
        if p.parent is not None:
            main = _d(by_id[p.parent])
            q["water.tee20_16" if main > d else f"water.tee{max(main, d)}"] += 1
            q[f"water.sleeve{main}"] += 2  # the main is cut by a tee
    return {k: v for k, v in q.items() if v}


def quantities(net: Network, plumbing: Plumbing) -> dict[str, float]:
    """Quantities by LINES keys (no zeros), in LINES order."""
    q: defaultdict[str, float] = defaultdict(float)
    water = [p for p in net.pipes if p.kind in ("cold", "hot")]
    sewer = net.pipes_of("sewer")
    for p in water:
        q[f"water.pipe{_d(p)}"] += p.total * (1 + RESERVE) / 1000
        q["water.insulation"] += p.length / 1000
        q["water.fixing"] += p.length // FIXING_STEP
        q["work.water_pipe"] += p.total / 1000
    for k, v in water_fittings(net).items():
        q[k] += v
    q["work.water_outlet"] = sum(q[f"water.outlet{d}"] for d in DIAMETERS)
    if net.distribution == "collector":
        q["water.collector"] = sum(c.outputs for c in net.collectors)
    from_riser = ["cold"] + (["hot"] if net.hot_source == "riser" else [])
    if water:
        q["water.valve"] = len(from_riser)
        q["water.filter"] = len(from_riser)
        q["water.reducer"] = len(from_riser)
        if plumbing.input is not None and plumbing.input.meters:
            q["water.meter"] = len(from_riser)
        q["work.input"] = 1
        q["work.pressure_test"] = 1
    if net.hot_source not in (None, "riser"):
        q["water.boiler_kit"] = 1
    ds = {p.id: p.d for p in sewer}
    for p in sewer:
        d = 110 if p.d >= 100 else 50
        q[f"sewer.pipe{d}"] += p.total * (1 + RESERVE) / 1000
        q[f"sewer.bend{d}"] += p.bends + drop_bends(p.rise)
        if p.parent is not None:
            main = 110 if ds[p.parent] >= 100 else 50
            q["sewer.tee110_50" if main > d else f"sewer.tee{main}"] += 1
        else:
            q["sewer.riser_tee"] += 1
            q["work.riser_tee"] += 1
            if d == 50:
                q["sewer.reducer"] += 1
        if p.bends > SEWER_BENDS:
            q["sewer.revision"] += 1
        q["sewer.fixing"] += p.length // FIXING_STEP
        q["work.sewer_pipe"] += p.total / 1000
    # Holes in partitions: water has its own (a pair in one), sewer has its own
    q["work.wall_hole"] = net.holes(("cold", "hot")) + net.holes(("sewer",))
    # Chases: per fixture one for water (above the highest water outlet plus the run along the
    # wall) and one for the drain if it is above the floor
    by_fixture: dict[str, list[float]] = {}
    for p in water:
        if p.target in {f.id for f in plumbing.fixtures}:
            outlet = max(
                (o.height for o in net.by_fixture(p.target) if o.kind != "sewer"), default=0.0
            )
            by_fixture.setdefault(p.target, []).append(outlet + p.wall_run)
    q["work.chase_pipe"] = sum(max(v) for v in by_fixture.values()) / 1000
    # Sewer: down the wall from the drain to the floor pipe and in the screed along walls goes in a
    # chase; above the floor by a wall it goes in a box
    q["work.chase_sewer"] = sum(p.rise for p in sewer if p.rise >= DRAIN_CHASE_MIN) / 1000
    q["work.chase_sewer_floor"] = sum(max(0.0, p.length - p.surface_length) for p in sewer) / 1000
    q["work.sewer_box"] = sum(p.surface_length for p in sewer) / 1000
    return {k: round(q[k], 2) for k in LINES if q.get(k)}


def build_estimate(
    net: Network, plumbing: Plumbing, prices: PriceSource, language: Language = "ru"
) -> Estimate:
    """Plumbing estimate: one row per quantity, prices from prices (price list over the service)."""
    lines = []
    for key, qty in quantities(net, plumbing).items():
        section, unit, ru, uk = LINES[key]
        quote = prices.lookup(key)
        p, exact = quote.price, quote.exact
        name = exact.name if exact and exact.name else (ru if language == "ru" else uk)
        lines.append(
            Line(
                section,
                key,
                name,
                unit_text(unit, language),
                qty,
                p.price if p else None,
                service=quote.service,
            )
        )
    lines.sort(key=lambda ln: SECTIONS.index(ln.section))
    return Estimate(tuple(lines), prices.currency)


def mock_prices() -> Mapping[str, float]:
    return MOCK_PRICES
