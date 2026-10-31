"""Каталог аппаратов щита: модели производителей — ширина в модулях DIN, габарит и вид.

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
    BREAKER = "breaker"  # автомат группы 1P
    DIFF = "diff"  # дифавтомат группы 1P+N


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
        _generic(DeviceKind.BREAKER, 1),
        _generic(DeviceKind.DIFF, 2, accent="#3a6ea5"),
    )
}

# Бренд → модели по виду аппарата. Новый бренд — словарь здесь же, по данным производителя
BRANDS: dict[str, dict[DeviceKind, CatalogModel]] = {"generic": GENERIC}


def model_for(kind: DeviceKind, brand: str = "generic") -> CatalogModel:
    """Модель аппарата бренда; нет у бренда — типовая."""
    return BRANDS.get(brand, {}).get(kind) or GENERIC[kind]
