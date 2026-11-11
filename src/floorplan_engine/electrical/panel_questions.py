"""The "Panel" stage questions (panel_*): backup, supply (phases and main breaker), backup bus
contents, a group split on the panel, the cable of a heavy appliance, the master switch (whether,
what it cuts, where), the backup power; with an inverter also the battery, solar panels and
the battery box location. Built by code; answers go to answers.yaml and
are applied by answers.apply_auto_answers."""

from __future__ import annotations

from floorplan_engine.electrical.loads import (
    cable_for,
    current,
    rating_for,
)
from floorplan_engine.electrical.master import is_master, master_on
from floorplan_engine.electrical.panel import (
    INVERTER_KW,
    BoardPanel,
    reserve_groups,
)
from floorplan_engine.electrical.panel_text import amps, kw, text
from floorplan_engine.model.intake import QSeverity, Question, Stage
from floorplan_engine.model.schema import Electrical
from floorplan_engine.model.texts import Language

AUTO_PREFIX = "panel_"  # ids of questions built by code; they are never written in intake.yaml
BACKUP_OPTIONS = ["none", "inverter", "plug", "station"]
# A "groups" answer goes into this panel field (validation/answers.apply_auto_answers)
GROUPS_FIELD = {f"{AUTO_PREFIX}reserve": "reserve", f"{AUTO_PREFIX}master_off": "master_off"}
# A "value" answer goes into a panel field as an int, except these (fractional kW)
FLOAT_FIELDS = frozenset({"backup_power"})


def panel_questions(
    elec: Electrical, panel: BoardPanel, language: Language, model: Electrical | None = None
) -> list[Question]:
    """Panel questions from the calculation, in the project language: backup and supply if unset;
    split groups; an appliance larger than its group breaker; default backup bus contents.
    model is the electrical before lines are split: the backup bus is answered by its groups."""
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
                    "none": text("q_backup_none", language),
                    "inverter": text("inverter", language),
                    "plug": text("q_backup_plug", language),
                    "station": text("q_backup_station", language),
                },
                assumption="inverter",
                text=text("q_backup", language),
            )
        )
    if setup.phases is None:
        out.append(
            Question(
                id=f"{AUTO_PREFIX}phases",
                stage=Stage.PANEL,
                target="panel.phases",
                answer="value",
                assumption=1.0,
                text=text("q_phases", language),
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
                text=text(
                    "q_input_3" if panel.phases == 3 else "q_input",
                    language,
                    r=panel.input.rating,
                    i=amps(panel.design_current),
                ),
            )
        )
    if panel.backup is not None and setup.backup_power is None:
        inverter = panel.backup == "inverter"
        out.append(
            Question(
                id=f"{AUTO_PREFIX}backup_power",
                stage=Stage.PANEL,
                target="panel.backup_power",
                answer="value",
                unit="кВт",
                # The inverter is counted at the typical power; a generator is not checked
                assumption=INVERTER_KW if inverter else None,
                text=text(
                    f"q_power_{panel.backup}",
                    language,
                    p=kw(panel.reserve_peak),
                    lim=f"{INVERTER_KW:g}",
                ),
            )
        )
    if panel.backup is not None and not setup.reserve:
        names = ", ".join(g.group for g in panel.groups if g.reserved) or "—"
        out.append(
            Question(
                id=f"{AUTO_PREFIX}reserve",
                stage=Stage.PANEL,
                severity=QSeverity.MINOR,
                answer="groups",
                options=list(reserve_groups(panel, model or elec)),
                text=text("q_reserve", language, names=names),
            )
        )
    if panel.dc is not None:
        out += _dc_questions(elec, panel, language)
    out += _master_questions(elec, panel, language, model)
    for g in panel.groups:
        if g.split_of == g.group:
            lines = [x for x in panel.groups if x.split_of == g.group]
            parts = "; ".join(
                text(
                    "q_split_line",
                    language,
                    g=x.group,
                    what=", ".join(ld.title for ld in x.loads),
                    p=kw(x.power),
                )
                for x in lines
            )
            out.append(
                Question(
                    id=f"{AUTO_PREFIX}split_{g.group}",
                    stage=Stage.PANEL,
                    severity=QSeverity.MAJOR,
                    text=text(
                        "q_split",
                        language,
                        g=g.group,
                        i=amps(current(sum(x.power for x in lines))),
                        r=g.breaker.rating,
                        n=len(lines),
                        parts=parts,
                        wet=text("q_split_wet", language) if g.wet else "",
                    ),
                )
            )
        if g.current > g.breaker.rating and len(g.loads) == 1:
            ld = g.loads[0]
            out.append(
                Question(
                    id=f"{AUTO_PREFIX}cable_{g.group}",
                    stage=Stage.PANEL,
                    severity=QSeverity.MAJOR,
                    text=text(
                        "q_cable",
                        language,
                        g=g.group,
                        what=ld.title,
                        p=kw(ld.power),
                        i=amps(g.current),
                        c=g.cable or "—",
                        r=g.breaker.rating,
                        cable=cable_for(g.current) or text("q_cable_more", language),
                        need=rating_for(g.current),
                    ),
                )
            )
    return out


def _master_questions(
    elec: Electrical, panel: BoardPanel, language: Language, model: Electrical | None
) -> list[Question]:
    """Master switch: whether it is wanted if unset; with it, what it cuts (default contents) and
    its place, while the model has no master switch point."""
    setup = elec.panel
    if setup.master is None:
        return [
            Question(
                id=f"{AUTO_PREFIX}master",
                stage=Stage.PANEL,
                target="panel.master",
                answer="choice",
                options=["yes", "no"],
                option_labels={
                    "yes": text("q_master_yes", language),
                    "no": text("q_master_no", language),
                },
                assumption="yes" if master_on(elec) else "no",
                text=text("q_master", language),
            )
        ]
    if not master_on(elec):
        return []
    out: list[Question] = []
    if not setup.master_off:
        names = ", ".join(g.group for g in panel.groups if g.master) or "—"
        out.append(
            Question(
                id=f"{AUTO_PREFIX}master_off",
                stage=Stage.PANEL,
                severity=QSeverity.MINOR,
                answer="groups",
                options=list(reserve_groups(panel, model or elec)),
                text=text("q_master_off", language, names=names),
            )
        )
    if not any(is_master(p) for p in elec.points):
        out.append(
            Question(
                id=f"{AUTO_PREFIX}master_place",
                stage=Stage.PANEL,
                severity=QSeverity.MINOR,
                text=text("q_master_place", language),
            )
        )
    return out


def _dc_questions(elec: Electrical, panel: BoardPanel, language: Language) -> list[Question]:
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
                option_labels={
                    "yes": text("q_npe_yes", language),
                    "no": text("q_npe_no", language),
                },
                assumption="yes",
                text=text("q_npe", language),
            )
        )
    if setup.inverter is None:
        ats = any(d.id == "KM1" for d in panel.devices)
        out.append(
            Question(
                id=f"{AUTO_PREFIX}inverter",
                stage=Stage.PANEL,
                target="panel.inverter",
                answer="choice",
                options=["hybrid", "basic"],
                option_labels={
                    "hybrid": text("q_inverter_hybrid", language),
                    "basic": text("q_inverter_basic", language),
                },
                assumption="hybrid",
                text=text(
                    "q_inverter",
                    language,
                    switch=text("q_inverter_ats" if ats else "q_inverter_bypass", language),
                ),
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
                text=text(
                    "q_battery",
                    language,
                    v=dc.voltage,
                    a=amps(dc.current),
                    p=kw(dc.power * 1000),
                    r=dc.rating,
                    c=f"{dc.cable:g}",
                ),
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
                text=text("q_pv", language),
            )
        )
    out.append(
        Question(
            id=f"{AUTO_PREFIX}dc_place",
            stage=Stage.PANEL,
            severity=QSeverity.MINOR,
            text=text("q_dc_place", language),
        )
    )
    return out
