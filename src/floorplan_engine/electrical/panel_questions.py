"""Вопросы этапа «Щит» (panel_*): резерв, ввод, состав резервной шины, разделённая на щите
группа, кабель тяжёлого прибора. Составляет код; ответы — в answers.yaml, накладывает
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

AUTO_PREFIX = "panel_"  # id вопросов, которые составляет код; в intake.yaml такие не пишутся
BACKUP_OPTIONS = ["none", "inverter", "plug"]


def cable_for(amps_: float) -> str | None:
    """Наименьшее сечение, для которого рекомендуемый автомат держит ток: «3x6»."""
    s = next((s for s, (rec, _) in sorted(CABLE_LIMITS.items()) if rec >= amps_), None)
    return f"3x{s:g}" if s is not None else None


def panel_questions(elec: Electrical, panel: BoardPanel) -> list[Question]:
    """Вопросы щита по расчёту: резерв и ввод, если не заданы; разделённые группы;
    прибор больше автомата своей группы; состав резервной шины по умолчанию."""
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
