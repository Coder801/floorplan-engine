"""Каталог щита: корпуса (боксы) и модели аппаратов производителей — ширина в модулях DIN,
габарит и вид.

Корпус (`Enclosure`) — реальный щит производителя: рядов, модулей в ряду и габарит; щит в
лицо рисуется в нём (просмотр, лист «Щит»), аппараты подбираются так, чтобы не выйти за
корпус (`electrical/panel.choose_enclosure`).

Аппарат щита (panel.Device) получает модель по бренду щита (`panel.brand` в electrical.yaml)
и виду аппарата; у бренда нет такой модели — берётся типовая (`generic`). Модель уходит
в страницу .epd (ключ `panel`): просмотр рисует аппарат по её виду (`style`) и цветам.

Сюда добавляются бренды и серии — только с данными из каталога производителя (ширина,
высота, цвета корпуса); артикулы не выдумываются.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeviceKind(StrEnum):
    INPUT = "input"  # вводной 2P
    RELAY = "relay"  # реле напряжения
    SPD = "spd"  # УЗИП
    RCD = "rcd"  # УЗО на несколько групп
    CHANGEOVER = "changeover"  # перекидной I-0-II или обходной
    ATS = "ats"  # АВР
    FEED = "feed"  # питание инвертора 2P
    OUTPUT = "output"  # выход инвертора 2P (AC OUT → АВР или переключатель)
    BREAKER = "breaker"  # автомат группы 1P
    DIFF = "diff"  # дифавтомат группы 1P+N
    DC_BATTERY = "dc_battery"  # автомат АКБ, DC 2P (щит АКБ у инвертора)
    DC_BREAKER = "dc_breaker"  # автомат строки солнечных панелей, DC 2P
    DC_SPD = "dc_spd"  # УЗИП строки солнечных панелей, DC (+, −, PE)


MODULE_MM = 17.5  # ширина модуля DIN, мм


@dataclass(frozen=True)
class CatalogModel:
    id: str  # «generic.breaker»
    brand: str
    series: str
    kind: DeviceKind
    modules: int
    height: float  # мм, по лицевой стороне
    style: str  # как рисовать: breaker, diff, rcd, relay, spd, changeover, ats, input, feed
    body: str = "#f4f4f2"  # цвет корпуса
    lever: str = "#2b2b2b"  # цвет рычага
    accent: str | None = None  # цвет вставки (у дифавтомата — кнопка «Тест»)

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "id": self.id,
            "brand": self.brand,
            "series": self.series,
            "modules": self.modules,
            "width": round(self.modules * MODULE_MM, 1),
            "height": self.height,
            "style": self.style,
            "body": self.body,
            "lever": self.lever,
        }
        if self.accent is not None:
            out["accent"] = self.accent
        return out


def _generic(kind: DeviceKind, modules: int, height: float = 85.0, **kw: str) -> CatalogModel:
    return CatalogModel(
        f"generic.{kind.value}", "generic", "", kind, modules, height, kind.value, **kw
    )


GENERIC: dict[DeviceKind, CatalogModel] = {
    m.kind: m
    for m in (
        _generic(DeviceKind.INPUT, 2),
        _generic(DeviceKind.RELAY, 3, 90.0),
        _generic(DeviceKind.SPD, 2, 90.0),
        _generic(DeviceKind.RCD, 2, accent="#3a6ea5"),
        _generic(DeviceKind.CHANGEOVER, 3, 90.0),
        _generic(DeviceKind.ATS, 4, 90.0),
        _generic(DeviceKind.FEED, 2),
        _generic(DeviceKind.OUTPUT, 2),
        _generic(DeviceKind.BREAKER, 1),
        _generic(DeviceKind.DIFF, 2, accent="#3a6ea5"),
        # DC-автомат АКБ на 80–250 А — шире модульного: полтора модуля на полюс
        _generic(DeviceKind.DC_BATTERY, 3, 90.0, accent="#c62828"),
        _generic(DeviceKind.DC_BREAKER, 2, accent="#c62828"),
        _generic(DeviceKind.DC_SPD, 3, 90.0),
    )
}


@dataclass(frozen=True)
class Enclosure:
    """Корпус щита: ряды DIN-реек по `per_row` модулей, наружный габарит, мм."""

    id: str  # «hager.VS212PD»
    brand: str
    series: str
    article: str  # артикул производителя; у подобранного по месту — пусто
    rows: int
    per_row: int
    width: float
    height: float
    depth: float
    pitch: float = 125.0  # шаг реек, мм
    body: str = "#f6f6f3"  # цвет корпуса

    @property
    def modules(self) -> int:
        return self.rows * self.per_row

    @property
    def title(self) -> str:
        if not self.article:
            return f"{self.rows}×{self.per_row}"
        return f"{self.brand.capitalize()} {self.series} {self.article}"

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "brand": self.brand,
            "series": self.series,
            "article": self.article,
            "title": self.title,
            "rows": self.rows,
            "per_row": self.per_row,
            "width": self.width,
            "height": self.height,
            "depth": self.depth,
            "pitch": self.pitch,
            "body": self.body,
        }


def _golf(rows: int, per_row: int, width: float, height: float) -> Enclosure:
    article = f"VS{rows}{per_row}PD"
    return Enclosure(
        f"hager.{article}", "hager", "Golf", article, rows, per_row, width, height, 99.0
    )


# Hager Golf, наружной установки, белая дверца, IP40 (hager.com/ua, карточки VS…PD):
# габарит В × Ш × Г; шаг реек 125 мм — разница высот одно- и двухрядного (252 → 377)
ENCLOSURES: tuple[Enclosure, ...] = (
    _golf(1, 12, 282.0, 252.0),
    _golf(2, 12, 282.0, 377.0),
    _golf(3, 12, 282.0, 500.0),
    _golf(4, 12, 282.0, 647.0),
    _golf(1, 18, 390.0, 252.0),
    _golf(2, 18, 390.0, 377.0),
    _golf(3, 18, 390.0, 500.0),
    _golf(4, 18, 390.0, 647.0),
)
ENCLOSURE_BY_ARTICLE = {e.article: e for e in ENCLOSURES}

RAIL_MARGIN = 37.5  # от стенки до рейки у корпуса, подобранного по месту, мм
TOP_BOTTOM = 126.0  # над первой и под последней осью рейки у такого корпуса, мм


def fitted_enclosure(rows: int, per_row: int) -> Enclosure:
    """Корпус по месту — когда аппараты не влезают ни в один щит каталога: те же поля и
    шаг реек, что у Golf."""
    width = per_row * MODULE_MM + 2 * RAIL_MARGIN
    height = 2 * TOP_BOTTOM + (rows - 1) * 125.0
    return Enclosure(f"fitted.{rows}x{per_row}", "", "", "", rows, per_row, width, height, 99.0)


# Бренд → модели по виду аппарата. Новый бренд — словарь здесь же, по данным производителя
BRANDS: dict[str, dict[DeviceKind, CatalogModel]] = {"generic": GENERIC}


def model_for(kind: DeviceKind, brand: str = "generic") -> CatalogModel:
    """Модель аппарата бренда; нет у бренда — типовая."""
    return BRANDS.get(brand, {}).get(kind) or GENERIC[kind]
