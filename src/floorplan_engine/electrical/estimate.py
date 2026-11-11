"""Electrical estimate: quantities come from the model (code), prices from the project price
list (prices.yaml).

There is no drawing, only a table: out/estimate.md, out/estimate.csv and out/estimate.xlsx
(Excel with formulas: change a price or a quantity and the sums recalculate).
Quantities come from the same calculation as the wiring sheet (wiring.py); there is no
separate product specification: the estimate without prices is the bill of quantities:

- cable by type, with a RESERVE margin; laying work by actual length;
- flush boxes and devices by wall device posts, frames by blocks;
- junction boxes (IP44 in wet rooms, a separate item); crimp connections: L, N, PE in every
  box plus one per key of each switch it feeds;
- cable fixings at FIXING_STEP along the routes;
- chases from wall_chases (shared by nearby drops): narrow (up to CHASE_NARROW cables) and
  wide ones are separate items; passes through walls from wall_holes;
- panel: enclosure and devices from the "Panel" sheet (panel.build_panel: kind and rating, as
  in the purchase device table), assembly by the modules of that set; no panel means one
  breaker per group; device prices by kind (breaker, diff, rcd, input…), with the rating as a
  key refinement (breaker.C16);
- lights, lighting outputs and appliance outputs by point, LED strip in metres;
- labelling: a tag at each end of each line; insulation resistance test with a report for each
  power group;
- rough light, if chosen (Electrical.rough_light): a lamp holder, a bulb and a rough switch per
  room with lights.

Work comes in two sections with their own totals (decision 2026-11-03): rough (`rough`),
before plaster and screed: chases, passes, laying cable and conduit, flush boxes, boxes with
crimping, panel recess and enclosure, labelling, insulation test; finishing (`finish`), after
the finish: filling the panel with devices, fitting the devices. An item's section is in LINES.

Prices are never invented: items with no price in the list stay in the estimate marked
"no price" and are left out of the total. LED profiles and power supplies are not described
in the model and are not in the estimate.
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import Field

from floorplan_engine.electrical.boxes import BOX_ORDER, BOX_TITLES
from floorplan_engine.electrical.panel import BoardPanel, device_name
from floorplan_engine.electrical.wiring import RESERVE
from floorplan_engine.electrical.wiring_model import Run, Wiring
from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.model.schema import (
    LIGHT_TYPES,
    Conduit,
    Electrical,
    PointType,
    StrictModel,
)
from floorplan_engine.model.texts import Language, tr

PRICES_FILE = "prices.yaml"  # the project price list lives in the project folder, next to room.yaml
ESTIMATE_MD = "estimate.md"
ESTIMATE_CSV = "estimate.csv"
ESTIMATE_XLSX = "estimate.xlsx"
XLSX_MONEY = "#,##0.00"
XLSX_QTY = "#,##0.0##"
XLSX_EDIT_FILL = "FFF4D6"  # cells edited by hand: price and quantity
FIXING_STEP = 400.0  # mm: cable fixing step along the route
CONDUIT_SIZES = ((1.5, 16), (2.5, 20), (6.0, 25), (1e9, 32))  # cross-section, mm² → conduit Ø, mm
SWITCHES = frozenset({PointType.SWITCH, PointType.PASS_SWITCH})
# Devices in flush boxes: one flush box per post, one frame per block
MOUNTED = frozenset(
    {PointType.SOCKET, PointType.SWITCH, PointType.PASS_SWITCH, PointType.DATA, PointType.TV}
)

Section = Literal["material", "rough", "finish"]
SECTIONS: tuple[Section, ...] = ("material", "rough", "finish")  # order in the estimate
WORK_PREFIX = "work."  # work items (services); the rest of LINES are materials

# Estimate items: key → section, unit, name (ru, uk). Keys with a parameter:
# cable.<type>, frame.<posts>, junction_box.<size>, junction_box_ip.<size>, panel devices
# <kind>.<rating> (breaker.C16); if there is no price with the parameter, the plain key is used
LINES: dict[str, tuple[Section, str, str, str]] = {
    "cable": ("material", "м", "Кабель {mark}", "Кабель {mark}"),
    "conduit": ("material", "м", "Гофротруба ПВХ Ø{n}", "Гофротруба ПВХ Ø{n}"),
    "socket_box": ("material", "шт", "Подрозетник", "Підрозетник"),
    "junction_box": ("material", "шт", "Коробка распаечная {mark}", "Коробка розподільча {mark}"),
    "junction_box_ip": (
        "material",
        "шт",
        "Коробка распаечная IP44 {mark}",
        "Коробка розподільча IP44 {mark}",
    ),
    "crimp": (
        "material",
        "шт",
        "Гильза и термоусадка (опрессовка)",
        "Гільза і термоусадка (опресування)",
    ),
    "cable_fixing": ("material", "шт", "Крепление кабеля", "Кріплення кабелю"),
    "board_enclosure": ("material", "шт", "Корпус щита", "Корпус щита"),
    # Panel devices by kind (DeviceKind); the row has the name and rating from the panel set
    "breaker": ("material", "шт", "Автомат 1P (на группу)", "Автомат 1P (на групу)"),
    "diff": ("material", "шт", "Дифавтомат 1P+N", "Дифавтомат 1P+N"),
    "rcd": ("material", "шт", "УЗО", "ПЗВ"),
    "input": ("material", "шт", "Вводной автомат", "Вступний автомат"),
    "relay": ("material", "шт", "Реле напряжения", "Реле напруги"),
    "spd": ("material", "шт", "УЗИП", "ПЗІП"),
    "changeover": ("material", "шт", "Переключатель резерва", "Перемикач резерву"),
    "ats": ("material", "шт", "АВР", "АВР"),
    "contactor": ("material", "шт", "Контактор модульный", "Контактор модульний"),
    "feed": ("material", "шт", "Автомат питания инвертора", "Автомат живлення інвертора"),
    "output": ("material", "шт", "Автомат выхода инвертора", "Автомат виходу інвертора"),
    "dc_battery": ("material", "шт", "Автомат АКБ DC", "Автомат АКБ DC"),
    "dc_breaker": ("material", "шт", "Автомат строки панелей DC", "Автомат рядка панелей DC"),
    "dc_spd": ("material", "шт", "УЗИП DC", "ПЗІП DC"),
    "dc_enclosure": ("material", "шт", "Корпус щита АКБ", "Корпус щита АКБ"),
    "socket": ("material", "шт", "Розетка с заземлением", "Розетка із заземленням"),
    "switch1": ("material", "шт", "Выключатель одноклавишный", "Вимикач одноклавішний"),
    "switch2": ("material", "шт", "Выключатель двухклавишный", "Вимикач двоклавішний"),
    "pass_switch": ("material", "шт", "Выключатель проходной", "Вимикач прохідний"),
    "data": ("material", "шт", "Розетка интернет", "Розетка інтернет"),
    "tv": ("material", "шт", "Розетка TV", "Розетка TV"),
    "frame": ("material", "шт", "Рамка {n}-постовая", "Рамка {n}-постова"),
    # Lights and outputs: names as in the legend (texts.symbol_*)
    "light": ("material", "шт", "", ""),
    "downlight": ("material", "шт", "", ""),
    "pendant": ("material", "шт", "", ""),
    "sconce": ("material", "шт", "", ""),
    "led_output": ("material", "шт", "", ""),
    "outlet": ("material", "шт", "", ""),
    "led_strip": ("material", "м", "", ""),
    "rough_holder": ("material", "шт", "Патрон E27 черновой", "Патрон E27 чорновий"),
    "rough_lamp": ("material", "шт", "Лампа E27 черновая", "Лампа E27 чорнова"),
    "rough_switch": ("material", "шт", "Выключатель черновой", "Вимикач чорновий"),
    "work.cable": ("rough", "м", "Прокладка кабеля", "Прокладання кабелю"),
    "work.conduit": ("rough", "м", "Укладка кабеля в гофротрубу", "Укладання кабелю в гофротрубу"),
    "work.chase": (
        "rough",
        "м",
        "Штроба узкая, 1–2 кабеля",
        "Штроба вузька, 1–2 кабелі",
    ),
    "work.chase_wide": (
        "rough",
        "м",
        "Штроба широкая, 3–4 кабеля",
        "Штроба широка, 3–4 кабелі",
    ),
    "work.wall_hole": (
        "rough",
        "шт",
        "Сверление прохода через стену",
        "Свердління проходу крізь стіну",
    ),
    "work.socket_box": (
        "rough",
        "шт",
        "Сверление и установка подрозетника",
        "Свердління і встановлення підрозетника",
    ),
    "work.junction_box": (
        "rough",
        "шт",
        "Монтаж коробки с опрессовкой",
        "Монтаж коробки з опресуванням",
    ),
    "work.board_install": ("rough", "шт", "Установка щита", "Встановлення щита"),
    "work.board_module": ("finish", "мод.", "Сборка щита", "Збирання щита"),
    "work.mechanism": ("finish", "шт", "Установка механизмов", "Встановлення механізмів"),
    "work.rough_light": (
        "rough",
        "шт",
        "Монтаж чернового света: патрон и лампа",
        "Монтаж чорнового світла: патрон і лампа",
    ),
    "work.rough_switch": (
        "rough",
        "шт",
        "Установка чернового выключателя",
        "Встановлення чорнового вимикача",
    ),
    "work.marking": (
        "rough",
        "шт",
        "Маркировка концов кабеля",
        "Маркування кінців кабелю",
    ),
    "work.insulation_test": (
        "rough",
        "гр.",
        "Замер сопротивления изоляции с протоколом",
        "Вимірювання опору ізоляції з протоколом",
    ),
}
# Item notes: an "i" icon next to the name in the viewer, a comment in Excel; without a price
# also "price to be confirmed"
HINTS: dict[str, dict[str, str]] = {
    "work.mechanism": {
        "ru": "Установка розеток, выключателей, интернет- и ТВ-выводов",
        "uk": "Встановлення розеток, вимикачів, інтернет- і ТВ-виводів",
    },
}
PRICE_TBD = {"ru": "Цена уточняется", "uk": "Ціна уточнюється"}
PRICE_SERVICE = {
    "ru": "Цена — из сервиса цен (пока имитация, не рыночная)",
    "uk": "Ціна — із сервісу цін (поки імітація, не ринкова)",
}
PARAM_KEYS = (
    "cable",
    "conduit",
    "frame",
    "junction_box",
    "junction_box_ip",
    *(k.value for k in DeviceKind),
)
# Lights and outputs: key → name in texts (as in the legend)
FIXTURES = {
    "light": "symbol_light",
    "downlight": "symbol_downlight",
    "pendant": "symbol_pendant",
    "sconce": "symbol_sconce",
    "led_output": "symbol_led_output",
    "outlet": "symbol_outlet",
    "led_strip": "legend_led_strip",
}
TEXT: dict[str, dict[str, str]] = {
    "material": {"ru": "Материалы", "uk": "Матеріали"},
    "rough": {"ru": "Черновые работы", "uk": "Чорнові роботи"},
    "finish": {"ru": "Чистовые работы", "uk": "Чистові роботи"},
    "work": {"ru": "Работы", "uk": "Роботи"},
    "head": {
        "ru": "| № | Наименование | Ед. | Кол. | Цена, {c} | Сумма, {c} |",
        "uk": "| № | Найменування | Од. | Кільк. | Ціна, {c} | Сума, {c} |",
    },
    "subtotal": {"ru": "Итого", "uk": "Разом"},
    "total": {"ru": "Всего", "uk": "Усього"},
    "no_price": {"ru": "нет цены", "uk": "немає ціни"},
    "unpriced": {
        "ru": "Без цены: {n} поз. — в итог не входят, нужна цена в {f}.",
        "uk": "Без ціни: {n} поз. — до підсумку не входять, потрібна ціна в {f}.",
    },
    "title": {"ru": "Смета электрики: {name}", "uk": "Кошторис електрики: {name}"},
    "sheet_title": {"ru": "Смета электрики", "uk": "Кошторис електрики"},
    "sheet_volumes": {"ru": "Ведомость объёмов электрики", "uk": "Відомість обсягів електрики"},
    "col_no": {"ru": "№", "uk": "№"},
    "col_name": {"ru": "Наименование", "uk": "Найменування"},
    "col_unit": {"ru": "Ед.", "uk": "Од."},
    "col_qty": {"ru": "Кол.", "uk": "Кільк."},
    "col_price": {"ru": "Цена, {c}", "uk": "Ціна, {c}"},
    "col_sum": {"ru": "Сумма, {c}", "uk": "Сума, {c}"},
    "section_total": {"ru": "Итого: {s}", "uk": "Разом: {s}"},
    "sheet_prices": {"ru": "Цены: {f}{date}", "uk": "Ціни: {f}{date}"},
    "note_prices": {"ru": "Цены: {f}{date}{note}", "uk": "Ціни: {f}{date}{note}"},
    "note_no_prices": {
        "ru": "Цен нет: {f} не найден — смета только с объёмами",
        "uk": "Цін немає: {f} не знайдено — кошторис лише з обсягами",
    },
    "note_service": {
        "ru": "Цены {n} поз. — из сервиса цен (пока имитация, не рыночные цены); остальные — {f}",
        "uk": "Ціни {n} поз. — із сервісу цін (поки імітація, не ринкові ціни); решта — {f}",
    },
    "note_service_all": {
        "ru": "Все цены — из сервиса цен (пока имитация, не рыночные цены): {f} нет",
        "uk": "Усі ціни — із сервісу цін (поки імітація, не ринкові ціни): {f} немає",
    },
    "note_cable": {
        "ru": "Кабель — с запасом {pct} %; прокладка — по фактической длине",
        "uk": "Кабель — із запасом {pct} %; прокладання — за фактичною довжиною",
    },
    "note_chases": {
        "ru": "Штробы: общая, если спуски ближе {d} мм, до {k} кабелей; до {n} кабелей — "
        "узкая (в гофре — одна гофра), больше — широкая; силовые и слаботочка — в разных "
        "штробах",
        "uk": "Штроби: спільна, якщо спуски ближче {d} мм, до {k} кабелів; до {n} кабелів — "
        "вузька (у гофрі — одна гофра), більше — широка; силові і слабкострумові — в різних "
        "штробах",
    },
    "note_holes": {
        "ru": "Проходы через стены — над дверями и проёмами для трасс по потолку, до {k} "
        "кабелей в отверстии; трассы по полу идут под проёмом без сверления",
        "uk": "Проходи крізь стіни — над дверима і прорізами для трас по стелі, до {k} "
        "кабелів в отворі; траси по підлозі йдуть під прорізом без свердління",
    },
    "note_board_tail": {
        "ru": "Выпуск кабеля в щите — до пола ({h} мм), на остальных подключениях — {e} мм",
        "uk": "Виведення кабелю в щиті — до підлоги ({h} мм), на інших підключеннях — {e} мм",
    },
    "note_direct": {
        "ru": "Отдельные линии от щита без коробок: {groups}",
        "uk": "Окремі лінії від щита без коробок: {groups}",
    },
    "note_wet": {
        "ru": "Коробки во влажных помещениях — IP44: {n} шт",
        "uk": "Коробки у вологих приміщеннях — IP44: {n} шт",
    },
    "note_conduit": {
        "ru": "Гофротруба: по полу — всегда, вся линия до точки; по потолку — если выбрана, "
        "участок по потолку, а с гофрой в стенах — и спуски в штробах; диаметр — по сечению кабеля",
        "uk": "Гофротруба: по підлозі — завжди, уся лінія до точки; по стелі — якщо обрана, "
        "ділянка по стелі, а з гофрою в стінах — і спуски в штробах; діаметр — за перерізом кабелю",
    },
    "note_fixing": {
        "ru": "Крепления кабеля — шаг {step} мм",
        "uk": "Кріплення кабелю — крок {step} мм",
    },
    "note_crimp": {
        "ru": "Опрессовка: в каждой коробке L, N, PE и по соединению на клавишу выключателя",
        "uk": "Опресування: у кожній коробці L, N, PE і по з'єднанню на клавішу вимикача",
    },
    "note_excluded": {
        "ru": "Не входит: профиль и блоки питания LED, монтаж светильников, ввод питания",
        "uk": "Не входить: профіль і блоки живлення LED, монтаж світильників, введення живлення",
    },
    "note_panel": {
        "ru": "Щит — по составу листа «Щит»: аппараты по видам и номиналам",
        "uk": "Щит — за складом аркуша «Щит»: апарати за видами і номіналами",
    },
    "note_board_kit": {
        "ru": "board_kit в {f} не используется: состав щита — с листа «Щит», цены аппаратов — "
        "ключами {keys}",
        "uk": "board_kit у {f} не використовується: склад щита — з аркуша «Щит», ціни апаратів — "
        "ключами {keys}",
    },
    "note_height": {
        "ru": "Высота потолка 2700 мм — допущение (в room.yaml не указана)",
        "uk": "Висота стелі 2700 мм — припущення (у room.yaml не вказана)",
    },
    "note_questions": {
        "ru": "Открытые вопросы по электрике: {ids} — объёмы могут измениться",
        "uk": "Відкриті питання з електрики: {ids} — обсяги можуть змінитися",
    },
}


def text(key: str, language: Language, **values: object) -> str:
    return TEXT[key][language].format(**values)


class Price(StrictModel):
    price: float = Field(ge=0)
    name: str | None = Field(default=None, description="Своё наименование вместо стандартного")


class BoardItem(StrictModel):
    """Deprecated: the panel set is computed by the "Panel" sheet, device prices use keys by kind
    (breaker, diff, rcd, input…). The field is still read so old price lists open."""

    name: str = Field(min_length=1)
    price: float = Field(ge=0)
    qty: int = Field(default=1, ge=1)
    modules: int = Field(default=0, ge=0, description="Ширина на DIN-рейке, модулей")


class PriceList(StrictModel):
    """prices.yaml: prices by item key (LINES), per unit, in the currency currency."""

    currency: str = "грн"
    date: str = Field(default="", description="Когда собраны цены")
    note: str = ""
    items: dict[str, float | Price] = Field(default_factory=dict)
    board_kit: list[BoardItem] = Field(
        default_factory=list, description="Устарело — не используется"
    )

    def price(self, key: str) -> Price | None:
        item = self.items.get(key)
        return Price(price=item) if isinstance(item, int | float) else item

    def lookup(self, key: str) -> Quote:
        """Price by key; with a parameter, also tries the key without it ("cable.3x4" → "cable")."""
        base, param = split_key(key)
        exact = self.price(key)
        return Quote(exact or (self.price(base) if param else None), exact, service=False)


@dataclass(frozen=True)
class Quote:
    """Price source answer: the price, the price for the exact key (its own name comes from it) and
    a flag that the price comes from the price service (pricing.py), not the price list."""

    price: Price | None
    exact: Price | None
    service: bool


class PriceSource(Protocol):
    """Where the estimate gets prices: a price list (PriceList), the price service or both merged
    (pricing.Prices).
    """

    @property
    def currency(self) -> str: ...

    def lookup(self, key: str) -> Quote: ...


BARE_CABLE = re.compile(r"(\d+)\s*[xх×]\s*(\d+(?:[.,]\d+)?)")
DEFAULT_CABLE = "ВВГнг"  # power cable without a brand in the model


def cable_title(mark: str) -> str:
    """Cable in the estimate: a bare section gets the default brand ("3x6" → "ВВГнг 3×6"), as in
    the studio price list; a mark with its own brand ("ВВГнг-LS 3x2.5", "UTP cat.6") stays."""
    bare = BARE_CABLE.fullmatch(mark.strip())
    if bare is None:
        return mark
    return f"{DEFAULT_CABLE} {bare[1]}×{bare[2].replace('.', ',')}"


def split_key(key: str) -> tuple[str, str]:
    """Split "cable.3x1.5" → ("cable", "3x1.5"); a key without a parameter → (key, "")."""
    base, _, param = key.partition(".")
    return (base, param) if base in PARAM_KEYS and param else (key, "")


def unknown_keys(prices: PriceList) -> list[str]:
    """Price list keys that match no estimate item (a typo or a foreign key)."""
    return [k for k in prices.items if split_key(k)[0] not in LINES]


ITEMS_LINE = re.compile(r"^items:\s*(#.*)?$")


def _money(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def edit_price_items(text: str, items: dict[str, float | None]) -> str:
    """Prices in the prices.yaml text, line by line, keeping comments: `key: 30  # …` → the new
    number, `key: { price: 30, name: … }` — only price; None removes the key's line; a missing
    key — a new line at the end of the items section. No items section — it is appended."""
    lines = text.splitlines()
    head = next((i for i, line in enumerate(lines) if ITEMS_LINE.match(line)), None)
    if head is None:
        lines += ["items:"]
        head = len(lines) - 1
    end = head + 1  # the section runs to the first unindented line that is not blank or a comment
    while end < len(lines) and (not lines[end].strip() or lines[end][:1] in (" ", "#")):
        end += 1
    last = head  # the section's last value line: new keys go after it
    for i in range(head + 1, end):
        if lines[i].strip() and not lines[i].lstrip().startswith("#"):
            last = i
    drop: set[int] = set()
    added: list[str] = []
    for key, value in items.items():
        pat = re.compile(rf"^(\s+){re.escape(key)}:\s*(.*)$")
        at = next((i for i in range(head + 1, end) if pat.match(lines[i])), None)
        if at is None:
            if value is not None:
                added.append(f"  {key}: {_money(value)}")
            continue
        if value is None:
            drop.add(at)
            continue
        m = pat.match(lines[at])
        assert m is not None
        indent, rest = m.groups()
        if rest.startswith("{"):
            rest = re.sub(r"price:\s*[\d.]+", f"price: {_money(value)}", rest, count=1)
        else:
            comment = re.search(r"\s+#.*$", rest)
            rest = _money(value) + (comment.group() if comment else "")
        lines[at] = f"{indent}{key}: {rest}"
    out = [line for i, line in enumerate(lines[: last + 1]) if i not in drop]
    out += added
    out += [line for i, line in enumerate(lines[last + 1 :], start=last + 1) if i not in drop]
    return "\n".join(out) + "\n"


@dataclass(frozen=True)
class Line:
    section: Section
    key: str
    name: str
    unit: str
    qty: float
    price: float | None  # None: not in the price list
    hint: str | None = None  # item note (HINTS)
    service: bool = False  # price from the price service (mock), not from the list

    @property
    def total(self) -> float | None:
        return None if self.price is None else self.qty * self.price


@dataclass(frozen=True)
class Estimate:
    lines: tuple[Line, ...]
    currency: str

    def subtotal(self, section: Section) -> float:
        return sum(ln.total or 0.0 for ln in self.lines if ln.section == section)

    @property
    def work(self) -> float:
        """All work: rough and finishing."""
        return self.subtotal("rough") + self.subtotal("finish")

    @property
    def total(self) -> float:
        return sum(self.subtotal(s) for s in SECTIONS)

    @property
    def unpriced(self) -> int:
        return sum(1 for ln in self.lines if ln.price is None)

    @property
    def from_service(self) -> int:
        return sum(1 for ln in self.lines if ln.service)


def conduit_diameter(mark: str) -> int:
    """Conduit by cable type, mm: up to 1.5 mm² Ø16, up to 2.5 Ø20, up to 6 Ø25, larger Ø32;
    an unreadable type (low-voltage) gets Ø20."""
    m = re.search(r"[x×]\s*([\d.,]+)", mark)
    section = float(m.group(1).replace(",", ".")) if m else 2.5
    return next((d for limit, d in CONDUIT_SIZES if section <= limit), CONDUIT_SIZES[-1][1])


def conduit_mm(run: Run, conduit: Conduit) -> float:
    """How much of a line goes in conduit (decisions 2026-11-01, 2026-11-08,
    docs/wiring-variants.md): on the floor always, the whole line including the rise to the
    point; on the ceiling as chosen (Electrical.conduit_level): the ceiling part, and with walls
    the drops in the chases too."""
    if run.route == "floor" or conduit == "walls":
        return run.length_mm
    return run.plan_mm if conduit == "ceiling" else 0.0


def quantities(wiring: Wiring, elec: Electrical) -> dict[str, float]:
    """Quantities by item key (no prices)."""
    q: dict[str, float] = {}
    for mark, m in wiring.by_mark().items():
        q[f"cable.{mark}"] = round(m * (1 + RESERVE), 1)
    conduit: dict[int, float] = {}
    for r in wiring.runs:
        d = conduit_diameter(r.mark)
        conduit[d] = conduit.get(d, 0.0) + conduit_mm(r, elec.conduit_level)
    for d in sorted(conduit):
        if conduit[d] > 0:
            q[f"conduit.{d}"] = round(conduit[d] / 1000 * (1 + RESERVE), 1)
    mounted = [p for p in elec.points if p.type in MOUNTED]
    posts = sum(p.count for p in mounted)
    q["socket_box"] = posts
    for b in sorted(wiring.boxes, key=lambda b: BOX_ORDER.index(b.size)):
        key = f"{'junction_box_ip' if b.wet else 'junction_box'}.{b.size}"
        q[key] = q.get(key, 0) + 1
    by_id = {p.id: p for p in elec.points}
    keys = sum(
        by_id[r.target].keys
        for r in wiring.runs
        if r.source != "board" and r.target in by_id and by_id[r.target].type in SWITCHES
    )
    q["crimp"] = 3 * len(wiring.boxes) + keys
    q["cable_fixing"] = math.ceil(sum(r.plan_mm for r in wiring.runs) / FIXING_STEP)
    if elec.board is not None:
        q["board_enclosure"] = 1
    q["breaker"] = len({r.group for r in wiring.runs})
    pieces: Counter[str] = Counter()
    for p in mounted:
        if p.type is PointType.SWITCH:
            pieces["switch2" if p.keys == 2 else "switch1"] += p.count
        else:
            pieces[p.type.value] += p.count
    for key in ("socket", "switch1", "switch2", "pass_switch", "data", "tv"):
        if pieces[key]:
            q[key] = pieces[key]
    for n, k in sorted(Counter(p.count for p in mounted).items()):
        q[f"frame.{n}"] = k
    fixtures: Counter[str] = Counter()
    for p in elec.points:
        if p.type.value in FIXTURES:
            fixtures[p.type.value] += p.count
    for key in FIXTURES:
        if fixtures[key]:
            q[key] = fixtures[key]
    led_m = sum(s.end - s.start for s in elec.led_strips) / 1000
    if led_m:
        q["led_strip"] = round(led_m, 2)
    rough_rooms = len({p.room for p in elec.points if p.type in LIGHT_TYPES})
    if elec.rough_light and rough_rooms:
        q["rough_holder"] = q["rough_lamp"] = q["rough_switch"] = rough_rooms
    q["work.cable"] = round(sum(r.length_mm for r in wiring.runs) / 1000, 1)
    in_conduit = sum(conduit_mm(r, elec.conduit_level) for r in wiring.runs)
    if in_conduit > 0:
        q["work.conduit"] = round(in_conduit / 1000, 1)
    q["work.chase"] = round(wiring.chase_length(wide=False) / 1000, 1)
    q["work.chase_wide"] = round(wiring.chase_length(wide=True) / 1000, 1)
    q["work.wall_hole"] = len(wiring.holes)
    q["work.socket_box"] = posts
    q["work.junction_box"] = len(wiring.boxes)
    if elec.board is not None:
        q["work.board_install"] = 1
    q["work.mechanism"] = sum(pieces.values())
    if elec.rough_light and rough_rooms:
        q["work.rough_light"] = q["work.rough_switch"] = rough_rooms
    q["work.marking"] = 2 * len(wiring.runs)
    q["work.insulation_test"] = len({r.group for r in wiring.runs if r.circuit == "power"})
    return {k: v for k, v in q.items() if v}


def build_estimate(
    wiring: Wiring,
    elec: Electrical,
    prices: PriceSource,
    language: Language = "ru",
    panel: BoardPanel | None = None,
) -> Estimate:
    """Estimate: one item per quantity. The panel follows the "Panel" sheet set (panel): a row per
    device kind and rating, assembly by the modules of the set; no panel means one breaker per
    group. prices is a price list or the list merged with the price service (pricing.Prices)."""
    q = quantities(wiring, elec)
    if panel is not None:
        q.pop("breaker", None)
    if "work.board_install" in q:  # assembly right after the panel installation
        modules = panel.modules if panel is not None else q.get("breaker", 0.0)
        items = list(q.items())
        at = next(k for k, (key, _) in enumerate(items) if key == "work.board_install") + 1
        items.insert(at, ("work.board_module", modules))
        q = dict(items)

    def line(key: str, qty: float, name: str | None = None) -> Line:
        base, param = split_key(key)
        section, unit, ru, uk = LINES[base]
        quote = prices.lookup(key)
        p, exact = quote.price, quote.exact
        if exact and exact.name:
            name = exact.name
        elif p and p.name and name is None:
            name = p.name
        elif name is None and base in FIXTURES:
            name = tr(FIXTURES[base], language)
        elif name is None:
            mark = cable_title(param) if base == "cable" else BOX_TITLES.get(param, param)
            name = (ru if language == "ru" else uk).format(mark=mark, n=param)
        hint = HINTS.get(base, {}).get(language)
        if hint and p is None:
            hint = f"{hint}. {PRICE_TBD[language]}"
        if quote.service and p is not None:
            hint = f"{hint}. {PRICE_SERVICE[language]}" if hint else PRICE_SERVICE[language]
        return Line(section, key, name, unit, qty, p.price if p else None, hint, quote.service)

    names: dict[str, str] = {}
    if panel is not None and panel.enclosure is not None:  # enclosure from the Panel sheet
        enc = panel.enclosure
        base = LINES["board_enclosure"][2 if language == "ru" else 3]
        names["board_enclosure"] = f"{base} {enc.title}, {enc.modules} мод."
    lines = [line(k, v, names.get(k)) for k, v in q.items()]
    if panel is not None:
        # Panel devices by kind and rating, in panel order; next to the enclosure
        counts: dict[tuple[str, str], tuple[str, int]] = {}
        for d in panel.all_devices:
            key = f"{d.kind.value}.{d.label}"
            name, n = counts.get((key, d.label), (device_name(d, language), 0))
            counts[(key, d.label)] = (name, n + 1)
        devices = [line(key, n, name) for (key, _), (name, n) in counts.items()]
        if panel.dc is not None:  # battery box enclosure after the devices
            enc = panel.dc.enclosure
            base = LINES["dc_enclosure"][2 if language == "ru" else 3]
            devices.append(line("dc_enclosure", 1, f"{base} {enc.title}, {enc.modules} мод."))
        at = next((k + 1 for k, ln in enumerate(lines) if ln.key == "board_enclosure"), len(lines))
        lines[at:at] = devices
    lines.sort(key=lambda ln: SECTIONS.index(ln.section))
    return Estimate(tuple(lines), prices.currency)


def format_number(x: float, digits: int = 2) -> str:
    text = f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text.removesuffix(",00") if digits else text


def write_markdown(
    est: Estimate, path: Path, title: str, notes: list[str], language: Language
) -> Path:
    def t(key: str, **values: object) -> str:
        return text(key, language, **values)

    out = [f"# {title}", ""]
    for section in SECTIONS:
        rows = [ln for ln in est.lines if ln.section == section]
        if not rows:
            continue
        out += [f"## {t(section)}", "", t("head", c=est.currency), "|---|---|---|---|---:|---:|"]
        for k, ln in enumerate(rows, 1):
            price = format_number(ln.price) if ln.price is not None else t("no_price")
            total = format_number(ln.total) if ln.total is not None else "—"
            qty = format_number(ln.qty, 1).removesuffix(",0")
            out.append(f"| {k} | {ln.name} | {ln.unit} | {qty} | {price} | {total} |")
        out += [f"| | **{t('subtotal')}** | | | | **{format_number(est.subtotal(section))}** |", ""]
    out += [f"**{t('total')}: {format_number(est.total)} {est.currency}**", ""]
    if est.unpriced:
        out += [t("unpriced", n=est.unpriced, f=PRICES_FILE), ""]
    out += [f"- {n}" for n in notes]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def write_csv(est: Estimate, path: Path) -> Path:
    """CSV for Excel: UTF-8 with BOM, ";" separator, decimal comma; section is the section
    (material, rough, finish)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["section", "key", "name", "unit", "qty", "price", "total"])
        for ln in est.lines:
            w.writerow(
                [
                    ln.section,
                    ln.key,
                    ln.name,
                    ln.unit,
                    f"{ln.qty:g}".replace(".", ","),
                    "" if ln.price is None else f"{ln.price:g}".replace(".", ","),
                    "" if ln.total is None else f"{ln.total:.2f}".replace(".", ","),
                ]
            )
    return path


def write_xlsx(
    est: Estimate,
    path: Path,
    title: str,
    notes: list[str],
    language: Language,
    extra: Callable[[Workbook], None] | None = None,
) -> Path:
    """Estimate in Excel: sections, row sum as a formula "qty × price", section totals and "Total"
    as formulas, prices and quantities highlighted (they get edited). An item without a price has
    an empty price with a note; once a price is entered it counts in the totals. extra adds its
    own sheets after the estimate (the work scope, work_scope.scope_sheet)."""

    def t(key: str, **values: object) -> str:
        return text(key, language, **values)

    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = t("sheet_title")[:31]
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    heads = [
        t("col_no"),
        t("col_name"),
        t("col_unit"),
        t("col_qty"),
        t("col_price", c=est.currency),
        t("col_sum", c=est.currency),
        "key",
    ]
    ws.append([])
    ws.append(heads)
    head_row = ws.max_row
    for cell in ws[head_row]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    edit = PatternFill("solid", start_color=XLSX_EDIT_FILL, end_color=XLSX_EDIT_FILL)
    grey = Font(color="999999", size=8)
    subtotals: list[str] = []
    for section in SECTIONS:
        rows = [ln for ln in est.lines if ln.section == section]
        if not rows:
            continue
        ws.append(["", t(section)])
        ws.cell(ws.max_row, 2).font = Font(bold=True)
        first = ws.max_row + 1
        for k, ln in enumerate(rows, 1):
            r = ws.max_row + 1
            ws.append([k, ln.name, ln.unit, ln.qty, ln.price, f'=IF(E{r}="","",D{r}*E{r})', ln.key])
            ws.cell(r, 4).number_format = XLSX_QTY
            ws.cell(r, 5).number_format = XLSX_MONEY
            ws.cell(r, 6).number_format = XLSX_MONEY
            ws.cell(r, 4).fill = edit
            ws.cell(r, 5).fill = edit
            ws.cell(r, 7).font = grey
            if ln.hint:
                ws.cell(r, 2).comment = Comment(ln.hint, "Shtroba")
            if ln.price is None:
                ws.cell(r, 5).comment = Comment(t("no_price"), "Shtroba")
        last = ws.max_row
        ws.append(["", t("section_total", s=t(section)), "", "", "", f"=SUM(F{first}:F{last})"])
        total_row = ws.max_row
        ws.cell(total_row, 2).font = Font(bold=True)
        ws.cell(total_row, 6).font = Font(bold=True)
        ws.cell(total_row, 6).number_format = XLSX_MONEY
        subtotals.append(f"F{total_row}")
    ws.append([])
    ws.append(
        [
            "",
            f"{t('total')}, {est.currency}",
            "",
            "",
            "",
            "=" + "+".join(subtotals) if subtotals else 0,
        ]
    )
    grand = ws.max_row
    for col in (2, 6):
        ws.cell(grand, col).font = Font(bold=True, size=12)
    ws.cell(grand, 6).number_format = XLSX_MONEY
    ws.append([])
    if est.unpriced:
        ws.append(["", t("unpriced", n=est.unpriced, f=PRICES_FILE)])
    for note in notes:
        ws.append(["", note])
    for letter, width in zip("ABCDEFG", (5, 48, 7, 10, 12, 14, 18), strict=True):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = f"A{head_row + 1}"
    if extra is not None:
        extra(wb)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
