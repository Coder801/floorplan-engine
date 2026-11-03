"""The "Panel" stage questions (panel_*): backup, supply, backup bus contents, a group split on the
panel, the cable of a heavy appliance; with an inverter also the battery, solar panels and
the battery box location. Built by code; answers go to answers.yaml and are applied by
answers.apply_auto_answers."""

from __future__ import annotations

from floorplan_engine.electrical.loads import (
    CABLE_LIMITS,
    current,
    rating_for,
)
from floorplan_engine.electrical.panel import (
    BoardPanel,
)
from floorplan_engine.electrical.panel_text import amps, kw
from floorplan_engine.model.intake import QSeverity, Question, Stage
from floorplan_engine.model.schema import Electrical

AUTO_PREFIX = "panel_"  # ids of questions built by code; they are never written in intake.yaml
BACKUP_OPTIONS = ["none", "inverter", "plug"]


def cable_for(amps_: float) -> str | None:
    """Smallest cross-section whose recommended breaker carries the current: "3x6"."""
    s = next((s for s, (rec, _) in sorted(CABLE_LIMITS.items()) if rec >= amps_), None)
    return f"3x{s:g}" if s is not None else None


def panel_questions(elec: Electrical, panel: BoardPanel) -> list[Question]:
    """Panel questions from the calculation: backup and supply if unset; split groups; an appliance
    larger than its group breaker; default backup bus contents."""
    out: list[Question] = []
    setup = elec.panel
    if setup.backup is None:
        out.append(
            Question(
                id=f"{AUTO_PREFIX}backup",
                stage=Stage.PANEL,
                target="panel.backup",
                answer="choice",
                options=BACKUP_OPTIONS,
                option_labels={
                    "none": "Без резерва",
                    "inverter": "Инвертор с АКБ",
                    "plug": "Генератор через силовую вилку",
                },
                assumption="inverter",
                text="Нужен ли резерв питания? Сейчас — гибридный инвертор с АКБ (допущение): "
                "none — без резерва, inverter — инвертор, plug — генератор через силовую вилку",
            )
        )
    if setup.input is None:
        out.append(
            Question(
                id=f"{AUTO_PREFIX}input",
                stage=Stage.PANEL,
                target="panel.input",
                answer="value",
                unit="А",
                assumption=float(panel.input.rating),
                text=f"Вводной автомат по техусловиям? Сейчас {panel.input.rating} А "
                f"(допущение); расчётный ток квартиры {amps(current(panel.calculated))} А",
            )
        )
    if panel.backup is not None and not setup.reserve:
        names = ", ".join(g.group for g in panel.groups if g.reserved) or "—"
        out.append(
            Question(
                id=f"{AUTO_PREFIX}reserve",
                stage=Stage.PANEL,
                severity=QSeverity.MINOR,
                text=f"Что держать на резерве? Сейчас: {names} — свет, холодильник, роутер, "
                "котёл, насос, ворота, розетки кухни (допущение). Список групп — panel.reserve",
            )
        )
    if panel.dc is not None:
        out += _dc_questions(elec, panel)
    for g in panel.groups:
        if g.split_of == g.group:
            lines = [x for x in panel.groups if x.split_of == g.group]
            parts = "; ".join(
                f"{x.group} — {', '.join(ld.title for ld in x.loads)} ({kw(x.power)} кВт)"
                for x in lines
            )
            total = current(sum(x.power for x in lines))
            protect = " Мокрая зона — каждая линия через дифавтомат 30 мА." if g.wet else ""
            out.append(
                Question(
                    id=f"{AUTO_PREFIX}split_{g.group}",
                    stage=Stage.PANEL,
                    severity=QSeverity.MAJOR,
                    text=f"{g.group}: {amps(total)} А на автомате {g.breaker.rating} А — на щите "
                    f"разделена на {len(lines)} линии: {parts}.{protect} Подтвердите — "
                    "второй кабель от щита перенесём в electrical.yaml",
                )
            )
        if g.current > g.breaker.rating and len(g.loads) == 1:
            ld = g.loads[0]
            need = rating_for(g.current)
            cable = cable_for(g.current) or "больше"
            out.append(
                Question(
                    id=f"{AUTO_PREFIX}cable_{g.group}",
                    stage=Stage.PANEL,
                    severity=QSeverity.MAJOR,
                    text=f"{g.group}: {ld.title} {kw(ld.power)} кВт — {amps(g.current)} А, "
                    f"а кабель {g.cable or '—'} и автомат {g.breaker.rating} А. Нужен кабель "
                    f"{cable} и автомат {need} А — или укажите мощность прибора (power у точки)",
                )
            )
    return out


def _dc_questions(elec: Electrical, panel: BoardPanel) -> list[Question]:
    """Battery box: battery voltage and solar strings if unset; inverter and battery location
    always, until answered (it is not on the plan)."""
    assert panel.dc is not None
    dc, setup, out = panel.dc, elec.panel, []
    if setup.npe_relay is None:
        out.append(
            Question(
                id=f"{AUTO_PREFIX}npe",
                stage=Stage.PANEL,
                target="panel.npe_relay",
                answer="choice",
                options=["yes", "no"],
                option_labels={"yes": "Да, связывает", "no": "Нет, поставить контактор N–PE"},
                assumption="yes",
                text="Связывает ли инвертор N с PE в резервном режиме (встроенное реле N–PE, "
                "включается в настройках)? Без этой связи УЗО и дифавтоматы на резерве не "
                "сработают: no — поставим контактор N–PE",
            )
        )
    if setup.inverter is None:
        switch = "АВР KM1" if any(d.id == "KM1" for d in panel.devices) else "обходной SA1"
        out.append(
            Question(
                id=f"{AUTO_PREFIX}inverter",
                stage=Stage.PANEL,
                target="panel.inverter",
                answer="choice",
                options=["hybrid", "basic"],
                option_labels={"hybrid": "Гибридный", "basic": "Без своего переключения"},
                assumption="hybrid",
                text=f"Какой инвертор? Сейчас гибридный (допущение) — сам переключает сеть и АКБ, "
                f"в щите {switch}. basic — без своего переключения: резерв через АВР",
            )
        )
    if setup.battery_voltage is None:
        out.append(
            Question(
                id=f"{AUTO_PREFIX}battery",
                stage=Stage.PANEL,
                target="panel.battery_voltage",
                answer="value",
                unit="В",
                assumption=float(dc.voltage),
                text=f"Напряжение АКБ инвертора? Сейчас {dc.voltage} В (допущение): ток разряда "
                f"{amps(dc.current)} А при {kw(dc.power * 1000)} кВт — автомат АКБ {dc.rating} А, "
                f"кабель 2×{dc.cable:g} мм²",
            )
        )
    if setup.pv_strings is None:
        out.append(
            Question(
                id=f"{AUTO_PREFIX}pv",
                stage=Stage.PANEL,
                target="panel.pv_strings",
                answer="value",
                assumption=0.0,
                text="Есть ли солнечные панели? Сейчас нет (допущение). Число строк панелей "
                "на инвертор (0–2): у каждой — DC-автомат и УЗИП в щите АКБ",
            )
        )
    out.append(
        Question(
            id=f"{AUTO_PREFIX}dc_place",
            stage=Stage.PANEL,
            severity=QSeverity.MINOR,
            text="Где стоят инвертор, щит АКБ и АКБ? Сейчас — рядом с основным щитом "
            "(допущение): от этого — длина кабелей GRID, LOAD и АКБ",
        )
    )
    return out
