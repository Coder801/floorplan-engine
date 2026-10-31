"""Щит в лицо: состав щита по схеме и резерву, аппараты групп, слабые места, ряды DIN,
роспись потребителей (out/panel-loads.csv).

Только расчёт по модели, без рисования (рисует drawing/panel.py; для просмотра —
epd/panel_data.py). Потребители и автоматы групп — electrical/loads.py, вопросы этапа —
electrical/panel_questions.py, надписи — electrical/panel_text.py.

- Состав щита — по схеме (`panel.scheme`, решение 2026-10-27): economy — ввод и группы,
  мокрые зоны под одним УЗО, резерв — ручным переключателем; standard — плюс реле напряжения,
  мокрые зоны дифавтоматами, резерв через АВР; premium — плюс УЗИП, все группы
  дифавтоматами, характеристика B (кроме моторной нагрузки — C).
- Резерв (`panel.backup`) — от схемы отдельно: не задан — гибридный инвертор допущением
  и вопрос. Резервная шина — свет, холодильник, роутер, котёл, насос, ворота, розетки кухни.
- Слабые места — автомат больше, чем держит кабель, тяжёлый потребитель в общей группе,
  расчётный ток выше вводного, нет селективности, резерв меньше нагрузки.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from floorplan_engine.electrical.loads import (
    CABLE_LIMITS,
    SOCKETS_A,
    Breaker,
    PanelGroup,
    current,
    demand_factor,
    panel_groups,
    rating_for,
)
from floorplan_engine.electrical.panel_text import KIND_NAME, amps, kw, text
from floorplan_engine.model.panel_catalog import CatalogModel, DeviceKind, model_for
from floorplan_engine.model.schema import Electrical, PanelScheme, Plan
from floorplan_engine.model.texts import Language

INPUT_A = 63  # вводной автомат, если в модели его нет (допущение, решение 2026-10-27)
RCD_A = 40  # УЗО на мокрые зоны в economy


@dataclass(frozen=True)
class Device:
    """Аппарат на DIN-рейке."""

    id: str  # QS1, KV1, FV1, QD1, SA1, KM1, QF4
    kind: DeviceKind
    label: str  # что написано на аппарате: «C16», «40 А 30 мА»
    title: str  # что это
    group: str | None = None  # группа щита у автомата и дифавтомата
    feeds: tuple[str, ...] = ()  # группы под УЗО
    assumed: bool = False
    reserve: bool = False  # на резервной шине
    brand: str = "generic"  # бренд щита: модель — из каталога (panel_catalog)

    @property
    def model(self) -> CatalogModel:
        return model_for(self.kind, self.brand)

    @property
    def modules(self) -> int:
        return self.model.modules

    @property
    def key(self) -> str:
        """Объект чертежа: группа — «device:QF4», остальное — «device:QS1»."""
        return f"device:{self.group or self.id}"


@dataclass(frozen=True)
class Warning:
    severity: str  # major | minor
    text: dict[str, str]  # по языкам: ru для отчёта, язык проекта — для листа
    group: str | None = None


@dataclass(frozen=True)
class BoardPanel:
    """Щит целиком: группы, аппараты по порядку, итоги и слабые места."""

    scheme: PanelScheme
    backup: str | None  # inverter | plug; None — без резерва
    backup_assumed: bool  # резерв не задан — инвертор допущением
    groups: tuple[PanelGroup, ...]
    devices: tuple[Device, ...]
    input: Breaker
    installed: float  # Вт
    demand: float  # коэффициент спроса
    warnings: tuple[Warning, ...]
    power_limit: float | None  # выделенная мощность, кВт
    backup_power: float | None

    @property
    def calculated(self) -> float:
        return self.installed * self.demand

    @property
    def modules(self) -> int:
        return sum(d.modules for d in self.devices)

    @property
    def reserve_power(self) -> float:
        return sum(g.power for g in self.groups if g.reserved)


MODE_SCHEME: dict[str, PanelScheme] = {
    "economy": "economy",
    "standard": "standard",
    "proper": "premium",
}


def scheme_of(elec: Electrical) -> PanelScheme:
    if elec.panel.scheme is not None:
        return elec.panel.scheme
    return MODE_SCHEME[elec.mode]


def backup_of(elec: Electrical) -> tuple[str | None, bool]:
    """Резерв и допущение ли он: не задан — гибридный инвертор (решение 2026-10-27)."""
    b = elec.panel.backup
    if b is None:
        return "inverter", True
    return (None if b == "none" else b), False


def _group_devices(
    groups: Sequence[PanelGroup], scheme: PanelScheme, reserve: bool, lang: Language, rcds: int
) -> list[Device]:
    """Аппараты групп одной шины: в economy мокрые — под общим УЗО в конце, в proper
    свет — автоматами, остальное — дифавтоматами."""
    out: list[Device] = []
    under_rcd: list[PanelGroup] = []
    for g in groups:
        if scheme == "economy" and g.rcd is not None:
            under_rcd.append(g)
            continue
        kind = DeviceKind.DIFF if g.rcd is not None else DeviceKind.BREAKER
        label = g.breaker.label + (f" {g.rcd}" if g.rcd else "")
        out.append(Device(g.group, kind, label, g.purpose, g.group, (), g.breaker.assumed, reserve))
    if under_rcd:
        name = f"QD{rcds + 1}"
        rating = max(RCD_A, max(g.breaker.rating for g in under_rcd))
        rcd_label = f"{rating_for(rating, RCD_A)} А 30 мА"
        title = text("rcd_wet", lang)
        feeds = tuple(g.group for g in under_rcd)
        out.append(Device(name, DeviceKind.RCD, rcd_label, title, None, feeds, True, reserve))
        for g in under_rcd:
            out.append(
                Device(
                    g.group,
                    DeviceKind.BREAKER,
                    g.breaker.label,
                    g.purpose,
                    g.group,
                    (),
                    g.breaker.assumed,
                    reserve,
                )
            )
    return out


def build_panel(plan: Plan, elec: Electrical) -> BoardPanel | None:
    """Щит по модели; групп нет — None."""
    lang = plan.language
    setup = elec.panel
    scheme = scheme_of(elec)
    backup, backup_assumed = backup_of(elec)
    groups = panel_groups(plan, elec, scheme, backup is not None)
    if not groups:
        return None
    installed = sum(g.power for g in groups)
    demand = demand_factor(installed / 1000)
    inp = Breaker("C", setup.input or INPUT_A, setup.input is None)
    relay = setup.voltage_relay if setup.voltage_relay is not None else scheme != "economy"
    spd = setup.spd if setup.spd is not None else scheme == "premium"
    ats = setup.ats if setup.ats is not None else scheme != "economy"

    devices = [Device("QS1", DeviceKind.INPUT, f"{inp.label} 2P", text("input", lang))]
    if relay:
        label = f"{inp.rating} А"
        devices.append(Device("KV1", DeviceKind.RELAY, label, text("relay", lang)))
    if spd:
        devices.append(Device("FV1", DeviceKind.SPD, "T2 20 кА", text("spd", lang)))
    main = [g for g in groups if not g.reserved]
    reserved = [g for g in groups if g.reserved]
    devices += _group_devices(main, scheme, False, lang, 0)
    if backup is not None:
        if backup == "inverter":
            devices.append(
                Device("QS2", DeviceKind.FEED, f"C{SOCKETS_A * 2} 2P", text("inverter_feed", lang))
            )
        if ats:
            devices.append(Device("KM1", DeviceKind.ATS, "АВР", text("ats", lang), reserve=True))
        else:
            key = "bypass" if backup == "inverter" else "changeover"
            devices.append(
                Device("SA1", DeviceKind.CHANGEOVER, "I-0-II", text(key, lang), reserve=True)
            )
        rcds = sum(1 for d in devices if d.kind is DeviceKind.RCD)
        devices += _group_devices(reserved, scheme, True, lang, rcds)

    devices = [replace(d, brand=setup.brand) for d in devices]
    panel = BoardPanel(
        scheme,
        backup,
        backup_assumed,
        tuple(groups),
        tuple(devices),
        inp,
        installed,
        demand,
        (),
        setup.power,
        setup.backup_power,
    )
    return replace(panel, warnings=tuple(weak_spots(panel, relay)))


def _both(key: str, **kw_: object) -> dict[str, str]:
    return {lang: text(key, lang, **kw_) for lang in ("ru", "uk")}


def weak_spots(panel: BoardPanel, relay: bool) -> list[Warning]:
    """Слабые места щита: сначала по группам, потом по вводу и резерву."""
    out: list[Warning] = []
    for g in panel.groups:
        b = g.breaker
        if g.split_of is not None and g.group == g.split_of:
            msg = _both(
                "w_split", g=g.group, n=sum(1 for x in panel.groups if x.split_of == g.group)
            )
            out.append(Warning("major", msg, g.group))
        if g.current > b.rating and len(g.loads) == 1:
            ld, i = g.loads[0], amps(g.current)
            need = rating_for(g.current)
            msg = _both("w_single", g=g.group, what=ld.title, i=i, r=b.rating, need=need)
            out.append(Warning("major", msg, g.group))
        elif g.current > b.rating:
            msg = _both("w_overload", g=g.group, i=amps(g.current), r=b.rating)
            out.append(Warning("major", msg, g.group))
        if g.section is None:
            out.append(Warning("minor", _both("w_no_cable", g=g.group), g.group))
        elif g.section in CABLE_LIMITS:
            rec, top = CABLE_LIMITS[g.section]
            c = g.cable
            if b.rating > top:
                out.append(
                    Warning("major", _both("w_cable", g=g.group, r=b.rating, c=c, m=top), g.group)
                )
            elif b.rating > rec:
                out.append(
                    Warning(
                        "minor", _both("w_cable_soft", g=g.group, r=b.rating, c=c, m=rec), g.group
                    )
                )
        heavy = [ld for ld in g.loads if ld.heavy]
        if heavy and len(g.loads) > 1:
            for ld in heavy:
                out.append(
                    Warning(
                        "major",
                        _both("w_heavy_shared", g=g.group, what=ld.title, p=kw(ld.power)),
                        g.group,
                    )
                )
        if b.rating >= panel.input.rating:
            out.append(
                Warning(
                    "major", _both("w_select", g=g.group, r=b.rating, i=panel.input.rating), g.group
                )
            )
    calc_a = current(panel.calculated)
    if calc_a > panel.input.rating:
        out.append(Warning("major", _both("w_total", i=amps(calc_a), r=panel.input.rating)))
    if panel.power_limit is not None and panel.calculated / 1000 > panel.power_limit:
        out.append(
            Warning("major", _both("w_power", p=kw(panel.calculated), lim=f"{panel.power_limit:g}"))
        )
    if panel.input.assumed:
        out.append(Warning("minor", _both("w_input_assumed", r=panel.input.rating)))
    if not relay:
        out.append(Warning("minor", _both("w_no_relay")))
    if panel.backup is not None:
        res = panel.reserve_power
        if panel.backup_power is None:
            out.append(Warning("minor", _both("w_backup_unknown", p=kw(res))))
        elif res / 1000 > panel.backup_power:
            out.append(
                Warning("major", _both("w_backup", p=kw(res), lim=f"{panel.backup_power:g}"))
            )
        if panel.backup == "plug":
            out.append(Warning("minor", _both("w_plug")))
    return out


def device_name(d: Device, language: Language) -> str:
    """Аппарат для закупки: «Автомат 1P C16», «Вводной автомат, C63 2P» — в смете и в
    таблице аппаратов на закупку одинаково."""
    kind = KIND_NAME.get(d.kind)
    return f"{kind[language]} {d.label}" if kind is not None else f"{d.title}, {d.label}"


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def row_modules(devices: Sequence[Device]) -> int:
    """Модулей в рейке: 12, если хватает четырёх реек, иначе 18 или 24."""
    total = sum(d.modules for d in devices)
    return next((n for n in (12, 18, 24) if ceil_div(total, n) <= 4), 24)


def din_rows(devices: Sequence[Device], per_row: int | None = None) -> list[list[Device]]:
    """Аппараты по DIN-рейкам по порядку; аппарат не делится между рейками, резервная
    шина начинается с новой рейки."""
    if per_row is None:
        per_row = row_modules(devices)
    rows: list[list[Device]] = [[]]
    used = 0
    reserve = False
    for d in devices:
        fresh = d.reserve and not reserve  # резервная шина — со своей рейки
        reserve = reserve or d.reserve
        if (used + d.modules > per_row or fresh) and rows[-1]:
            rows.append([])
            used = 0
        rows[-1].append(d)
        used += d.modules
    return rows


def write_loads(panel: BoardPanel, path: Path) -> Path:
    """Роспись потребителей в CSV: группа, аппарат, точка, помещение, потребитель, мощность
    и откуда она (source — из модели, typical — типовая, допущение)."""
    devices = {d.group: d for d in panel.devices if d.group}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "group",
                "device",
                "cable",
                "point",
                "room",
                "consumer",
                "count",
                "watts",
                "power_from",
            ]
        )
        for g in panel.groups:
            label = devices[g.group].label if g.group in devices else g.breaker.label
            for ld in g.loads:
                w.writerow(
                    [
                        g.group,
                        label,
                        g.cable,
                        ld.point,
                        ld.room,
                        ld.title,
                        ld.count,
                        f"{ld.power:g}",
                        "typical" if ld.assumed else "source",
                    ]
                )
    return path


def scheme_title(panel: BoardPanel, language: Language) -> str:
    """«преміум, резерв: інвертор*»: схема и резерв, допущение — «*»."""
    out = text(panel.scheme, language)
    if panel.backup is not None:
        out += ", " + text(f"with_{panel.backup}", language) + ("*" if panel.backup_assumed else "")
    return out


def color_of(group: str | None, colors: dict[str, int]) -> int | None:
    """Цвет группы; линия разделённой группы (QF8.2) — цветом группы (QF8)."""
    if group is None:
        return None
    return colors.get(group, colors.get(group.split(".")[0]))


# --- Вопросы по щиту -----------------------------------------------------------
