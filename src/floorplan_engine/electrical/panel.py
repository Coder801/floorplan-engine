"""Щит в лицо: состав щита по схеме и резерву, аппараты групп, слабые места, ряды DIN,
роспись потребителей (out/panel-loads.csv).

Только расчёт по модели, без рисования (рисует drawing/panel.py; для просмотра —
epd/panel_data.py). Потребители и автоматы групп — electrical/loads.py, вопросы этапа —
electrical/panel_questions.py, надписи — electrical/panel_text.py.

- Состав щита — по схеме (`panel.scheme`, решение 2026-10-27): economy — ввод, реле
  напряжения и группы, мокрые зоны под одним УЗО; standard — мокрые зоны дифавтоматами;
  premium — плюс УЗИП, все группы дифавтоматами, характеристика B (кроме моторной
  нагрузки — C). Реле напряжения — во всех схемах (решение 2026-11-01).
- Резерв (`panel.backup`) — от схемы отдельно: не задан — гибридный инвертор допущением
  и вопрос. Переключатель — по источнику: гибридный инвертор сам переключает сеть и АКБ —
  обходной переключатель, инвертор без своего переключения (`inverter: basic`) — АВР,
  генератор — перекидной рубильник; выход инвертора — своим автоматом (QS3). Связь N–PE в
  резервном режиме (`npe_relay`) не задана или нет — слабое место: УЗО на резерве не
  сработают. Резервная шина — свет, холодильник, роутер, котёл, насос, ворота, розетки кухни.
- Слабые места — автомат больше, чем держит кабель, тяжёлый потребитель в общей группе,
  расчётный ток выше вводного, нет селективности, резерв меньше нагрузки.
- Щит АКБ (`DcBox`) — у гибридного инвертора отдельным боксом рядом с ним: автомат АКБ
  по току разряда, автоматы и УЗИП строк солнечных панелей (`panel.pv_strings`); напряжение
  АКБ и мощность инвертора без данных — 48 В и 5 кВт допущением. Резервные группы остаются
  в основном щите — за АВР или переключателем.
- Корпус — реальный щит каталога (`panel.enclosure` или самый маленький, куда влезают
  аппараты): рейки по видам аппаратов (`panel_rows`), аппарат не делится между рейками и не
  выходит за корпус; не влез ни в один — корпус по месту и замечание.
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
from floorplan_engine.model.panel_catalog import (
    ENCLOSURE_BY_ARTICLE,
    ENCLOSURES,
    CatalogModel,
    DeviceKind,
    Enclosure,
    fitted_enclosure,
    model_for,
)
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
    enclosure: Enclosure | None = None  # корпус щита; None — до подбора
    rows: tuple[tuple[Device, ...], ...] = ()  # аппараты по рейкам корпуса, сверху вниз
    dc: DcBox | None = None  # щит АКБ у инвертора; без инвертора — None

    @property
    def calculated(self) -> float:
        return self.installed * self.demand

    @property
    def modules(self) -> int:
        return sum(d.modules for d in self.devices)

    @property
    def reserve_power(self) -> float:
        return sum(g.power for g in self.groups if g.reserved)

    @property
    def all_devices(self) -> tuple[Device, ...]:
        """Аппараты щита и щита АКБ — для таблицы аппаратов и сметы."""
        return self.devices + (self.dc.devices if self.dc is not None else ())


INVERTER_KW = 5.0  # мощность инвертора без данных (допущение)
BATTERY_V = 48  # напряжение АКБ без данных (допущение)
DC_RATINGS = (63, 80, 100, 125, 160, 200, 250)  # ряд DC-автоматов АКБ, А
# Медный одножильный кабель АКБ по автомату (короткий, до 3 м), мм²
BATTERY_CABLE = {63: 16, 80: 25, 100: 25, 125: 35, 160: 50, 200: 70, 250: 95}
PV_A = 16  # автомат строки панелей, А DC


@dataclass(frozen=True)
class DcBox:
    """Щит АКБ у гибридного инвертора: АКБ, автомат АКБ, строки солнечных панелей."""

    devices: tuple[Device, ...]
    enclosure: Enclosure
    rows: tuple[tuple[Device, ...], ...]
    voltage: int  # В
    voltage_assumed: bool
    capacity: float | None  # кВт·ч
    power: float  # мощность инвертора, кВт
    power_assumed: bool
    current: float  # ток разряда АКБ на полной мощности, А
    rating: int  # автомат АКБ, А
    cable: float  # сечение кабеля АКБ, мм²
    pv_strings: int


def build_dc(elec: Electrical, lang: Language) -> DcBox:
    """Щит АКБ: ток разряда — мощность инвертора на напряжение АКБ; автомат — ближайший
    из ряда с запасом 10 %, кабель — по автомату; строка панелей — автомат и УЗИП."""
    setup = elec.panel
    voltage = setup.battery_voltage or BATTERY_V
    power = setup.backup_power or INVERTER_KW
    amps_ = power * 1000 / voltage
    rating = next((r for r in DC_RATINGS if r >= amps_ * 1.1), DC_RATINGS[-1])
    devices = [Device("QB1", DeviceKind.DC_BATTERY, f"{rating} А DC 2P", text("dc_battery", lang))]
    strings = setup.pv_strings or 0
    for k in range(1, strings + 1):
        devices.append(
            Device(f"QP{k}", DeviceKind.DC_BREAKER, f"{PV_A} А DC 2P", text("dc_pv", lang, n=k))
        )
        devices.append(Device(f"FP{k}", DeviceKind.DC_SPD, "PV 1000 В", text("dc_spd", lang, n=k)))
    devices = [replace(d, brand=setup.brand) for d in devices]
    enclosure, rows, _ = choose_enclosure(devices)
    return DcBox(
        tuple(devices),
        enclosure,
        tuple(tuple(r) for r in rows),
        voltage,
        setup.battery_voltage is None,
        setup.battery_capacity,
        power,
        setup.backup_power is None,
        amps_,
        rating,
        BATTERY_CABLE[rating],
        strings,
    )


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
    # Реле напряжения — во всех схемах (решение 2026-11-01): защищает и квартиру, и вход
    # инвертора от обрыва нуля
    relay = setup.voltage_relay if setup.voltage_relay is not None else True
    spd = setup.spd if setup.spd is not None else scheme == "premium"
    # АВР — только у инвертора без своего переключения; гибридный сам переключает сеть и
    # АКБ — ему обходной переключатель; генератор по вилке запускают руками — переключатель
    ats = setup.ats if setup.ats is not None else backup == "inverter" and setup.inverter == "basic"

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
        if backup == "inverter":  # выход инвертора — своим автоматом до АВР или переключателя
            devices.append(
                Device("QS3", DeviceKind.OUTPUT, f"C{SOCKETS_A * 2} 2P", text("inverter_out", lang))
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
    enclosure, rows, fit_note = choose_enclosure(panel.devices, setup.enclosure)
    dc = build_dc(elec, lang) if backup == "inverter" else None
    panel = replace(panel, enclosure=enclosure, rows=tuple(tuple(r) for r in rows), dc=dc)
    warnings = weak_spots(panel, relay, setup.npe_relay)
    if fit_note is not None:
        warnings.append(fit_note)
    return replace(panel, warnings=tuple(warnings))


# Общие аппараты — в таком порядке на своей рейке; дальше рейки автоматов (и УЗО), ниже —
# дифавтоматов (двойная гребёнка L + N)
COMMON_KINDS = (
    DeviceKind.INPUT,
    DeviceKind.RELAY,
    DeviceKind.SPD,
    DeviceKind.CHANGEOVER,
    DeviceKind.ATS,
    DeviceKind.OUTPUT,
    DeviceKind.FEED,
)


def row_kind(d: Device) -> str:
    """Рейка аппарата: common — общие, double — дифавтоматы, single — остальное."""
    if d.kind in COMMON_KINDS:
        return "common"
    return "double" if d.kind is DeviceKind.DIFF else "single"


def panel_rows(devices: Sequence[Device], per_row: int) -> list[list[Device]] | None:
    """Аппараты по рейкам корпуса: общие, автоматы, дифавтоматы — каждый вид со своей рейки,
    внутри вида — по порядку (основные, потом резервные); аппарат не делится между рейками.
    Аппарат шире рейки — None."""
    rows: list[list[Device]] = []
    for kind in ("common", "single", "double"):
        devs = [d for d in devices if row_kind(d) == kind]
        if kind == "common":
            devs.sort(key=lambda d: COMMON_KINDS.index(d.kind))
        used = per_row + 1
        for d in devs:
            if d.modules > per_row:
                return None
            if used + d.modules > per_row:
                rows.append([])
                used = 0
            rows[-1].append(d)
            used += d.modules
    return rows


def choose_enclosure(
    devices: Sequence[Device], article: str | None = None
) -> tuple[Enclosure, list[list[Device]], Warning | None]:
    """Корпус щита и аппараты по его рейкам. Задан артикул и аппараты влезают — он; иначе
    самый маленький щит каталога, куда влезают (меньше модулей, потом ниже), с замечанием,
    если заданный не подошёл; не влезают никуда — корпус по месту и замечание."""
    asked = ENCLOSURE_BY_ARTICLE.get(article) if article else None
    order = sorted(ENCLOSURES, key=lambda e: (e.modules, e.height))
    if asked is not None:
        order.insert(0, asked)
    for enc in order:
        rows = panel_rows(devices, enc.per_row)
        if rows is not None and len(rows) <= enc.rows:
            note = None
            if asked is not None and enc is not asked:
                note = Warning("major", _both("w_enclosure", a=asked.article, b=enc.article))
            return enc, rows, note
    per_row = max(24, *(d.modules for d in devices))
    rows = panel_rows(devices, per_row) or [list(devices)]
    total = sum(d.modules for d in devices)
    note = Warning("major", _both("w_enclosure_none", m=total))
    return fitted_enclosure(len(rows), per_row), rows, note


def _both(key: str, **kw_: object) -> dict[str, str]:
    return {lang: text(key, lang, **kw_) for lang in ("ru", "uk")}


def weak_spots(panel: BoardPanel, relay: bool, npe: bool | None = True) -> list[Warning]:
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
    if panel.backup == "inverter" and not npe:
        out.append(Warning("major", _both("w_npe_unknown" if npe is None else "w_npe_no")))
    if panel.dc is not None and panel.dc.voltage_assumed:
        dc = panel.dc
        out.append(Warning("minor", _both("w_battery", v=dc.voltage, a=amps(dc.current))))
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
