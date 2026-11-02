"""Откуда смета берёт цены: прайс студии или проекта (prices.yaml) поверх сервиса цен.

Сервис цен — внешний (решение 2026-11-01): API анализа цен, микросервис или база, куда цены
попадают с сайтов поставщиков. Его ещё нет, и его место занимает имитация `MockPriceService`
с типовыми ценами по Киеву: смета всегда с ценами, а `prices.yaml` — поправки студии поверх
(свой ключ прайса важнее любой цены сервиса). Строки с ценой сервиса помечены в смете
(`Line.service`, подсказка «из сервиса цен (пока имитация)»), чтобы их не приняли за рыночные.
Настоящий клиент сервиса появится в `service/` (сеть — только там) и передастся в
`pipeline.build_project` / `estimate_project` тем же протоколом `PriceSource`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from floorplan_engine.electrical.boxes import BOX_TITLES
from floorplan_engine.electrical.estimate import (
    LINES,
    PRICES_FILE,
    Estimate,
    Price,
    PriceList,
    PriceSource,
    Quote,
    split_key,
)
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.model.texts import Language

CURRENCY = "грн"

# Имитация: грн за единицу позиции (ключи LINES), ориентир по Киеву осенью 2026 — не рыночные
# цены. Ключи с параметром считает mock_price: кабель — по сечению, рамки — по постам,
# коробки — по размеру, аппараты щита — по номиналу.
MOCK_PRICES: dict[str, float] = {
    "socket_box": 20,
    "crimp": 8,
    "cable_fixing": 2,
    "board_enclosure": 6000,
    "breaker": 140,
    "diff": 950,
    "rcd": 1100,
    "input": 850,
    "relay": 1900,
    "spd": 2500,
    "changeover": 900,
    "ats": 4500,
    "feed": 500,
    "output": 500,
    "dc_battery": 2600,
    "dc_breaker": 650,
    "dc_spd": 1400,
    "dc_enclosure": 1500,
    "socket": 180,
    "switch1": 150,
    "switch2": 190,
    "pass_switch": 210,
    "data": 250,
    "tv": 220,
    "light": 900,
    "downlight": 350,
    "pendant": 1500,
    "sconce": 1200,
    "led_output": 150,
    "outlet": 150,
    "led_strip": 250,
    "work.cable": 30,
    "work.conduit": 10,
    "work.chase": 200,
    "work.chase_wide": 300,
    "work.wall_hole": 150,
    "work.socket_box": 100,
    "work.junction_box": 450,
    "work.board_install": 2500,
    "work.board_module": 120,
    "work.mechanism": 120,
    "work.marking": 10,
    "work.insulation_test": 150,
}
CABLE_PER_MM2 = 10.0  # грн за метр на мм² суммарного сечения жил: 3×1,5 → 45, 3×2,5 → 75
BOX_PRICES = {"80": 40.0, "100x100": 60.0, "150x110": 110.0, "190x140": 180.0}
CONDUIT_PRICES = {16: 10.0, 20: 14.0, 25: 20.0, 32: 30.0}  # гофротруба ПВХ, грн за метр
IP_FACTOR = 2.0  # IP44 — вдвое дороже обычной
FRAME_FIRST, FRAME_NEXT = 60.0, 40.0  # рамка: первый пост и каждый следующий
HEAVY_A = 40  # номинал, с которого ввод, реле и автомат дороже
HEAVY = {"input": (650.0, 850.0), "relay": (1500.0, 1900.0), "breaker": (140.0, 220.0)}


def _rating(param: str) -> int | None:
    m = re.search(r"\d+", param)
    return int(m.group()) if m else None


def mock_price(key: str) -> float | None:
    """Цена имитации по ключу позиции; неизвестный ключ — None."""
    base, param = split_key(key)
    if base == "cable":
        m = re.fullmatch(r"(\d+)x([\d.,]+)", param.replace("×", "x"))
        if m is None:
            return None
        return round(CABLE_PER_MM2 * int(m.group(1)) * float(m.group(2).replace(",", ".")), 1)
    if base == "conduit":
        return CONDUIT_PRICES.get(_rating(param) or 20)
    if base == "frame":
        posts = _rating(param) or 1
        return FRAME_FIRST + FRAME_NEXT * (posts - 1)
    if base in ("junction_box", "junction_box_ip"):
        size = next((k for k, title in BOX_TITLES.items() if param in (k, title)), None)
        price = BOX_PRICES.get(size or "", BOX_PRICES["100x100"])
        return price * IP_FACTOR if base == "junction_box_ip" else price
    if base in HEAVY and param:
        light, heavy = HEAVY[base]
        rating = _rating(param)
        return heavy if rating is not None and rating > HEAVY_A else light
    return MOCK_PRICES.get(base)


@dataclass(frozen=True)
class MockPriceService:
    """Имитация сервиса цен: знает все позиции сметы, цены типовые и постоянные. extra —
    цены позиций других смет (сантехника, plumbing/estimate.MOCK_PRICES) по ключу."""

    currency: str = CURRENCY
    extra: Mapping[str, float] = field(default_factory=dict)

    def lookup(self, key: str) -> Quote:
        price = mock_price(key)
        if price is None:
            price = self.extra.get(key)
        return Quote(None if price is None else Price(price=price), None, service=True)


@dataclass(frozen=True)
class Prices:
    """Цены сметы: прайс студии или проекта (own, может не быть) поверх сервиса цен (service).
    Свой ключ, даже без номинала (`diff`), важнее точной цены сервиса (`diff.C16 30 мА`)."""

    own: PriceList | None = None
    service: PriceSource | None = None

    @property
    def currency(self) -> str:
        if self.own is not None:
            return self.own.currency
        return self.service.currency if self.service is not None else CURRENCY

    @property
    def priced(self) -> bool:
        """Есть откуда брать цены: иначе смета — ведомость объёмов."""
        return self.own is not None or self.service is not None

    def lookup(self, key: str) -> Quote:
        if self.own is not None:
            quote = self.own.lookup(key)
            if quote.price is not None:
                return quote
        if self.service is not None:
            return self.service.lookup(key)
        return Quote(None, None, False)


def price_notes(
    est: Estimate, prices: Prices, language: Language, f: str = PRICES_FILE, note: bool = False
) -> list[str]:
    """Откуда цены — первые примечания сметы на листе, в просмотре и в файлах: прайс (с датой
    и, если note, пометкой прайса), доля сервиса цен (имитация), позиции без цены."""
    out = []
    if prices.own is not None:
        date = f" ({prices.own.date})" if prices.own.date else ""
        if note:
            tail = f" — {prices.own.note}" if prices.own.note else ""
            out.append(estimate_text("note_prices", language, f=f, date=date, note=tail))
        else:
            out.append(estimate_text("sheet_prices", language, f=f, date=date))
    if est.from_service:
        key = "note_service" if prices.own is not None else "note_service_all"
        out.append(estimate_text(key, language, n=est.from_service, f=f))
    if est.unpriced:
        out.append(estimate_text("unpriced", language, n=est.unpriced, f=f))
    return out


def mock_covers_all_lines() -> list[str]:
    """Ключи позиций, для которых у имитации нет цены (тест: должен быть пуст)."""
    sample = {"cable": "cable.3x1.5", "frame": "frame.2", "conduit": "conduit.20"}
    return [k for k in LINES if mock_price(sample.get(k, k)) is None]
