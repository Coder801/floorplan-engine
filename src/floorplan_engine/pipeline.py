"""Конвейер проекта без вывода на экран: оценка, отчёт, сборка DXF, артефакта и PNG.

Общий для CLI и сервиса: CLI печатает результат, сервис кладёт его в состояние проекта.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ezdxf.document import Drawing
from ezdxf.filemanagement import readfile

from floorplan_engine.artifact import export_artifact
from floorplan_engine.assess import STAGE_FILES, StageResult, assess
from floorplan_engine.draw_electrical import group_key
from floorplan_engine.draw_wiring import write_chases, write_journal
from floorplan_engine.estimate import (
    ESTIMATE_CSV,
    ESTIMATE_MD,
    FIXING_STEP,
    PRICES_FILE,
    Estimate,
    PriceList,
    build_estimate,
    unknown_keys,
    write_csv,
    write_markdown,
)
from floorplan_engine.estimate import text as estimate_text
from floorplan_engine.intake import Stage
from floorplan_engine.layers import drawing_scale
from floorplan_engine.objects import (
    describe_objects,
    line_chains,
    line_groups,
    wire_titles,
    wiring_handles,
)
from floorplan_engine.preview import render_png, sheet_layouts
from floorplan_engine.report import REPORT_JSON, REPORT_MD, render_markdown, to_json
from floorplan_engine.scene3d import build_scene
from floorplan_engine.schema import Electrical, WiringEdits
from floorplan_engine.sheets import build_project_document, document_scale, sheet_png_name
from floorplan_engine.side import side_tables
from floorplan_engine.validate import (
    WIRING_FILE,
    Issue,
    Report,
    Severity,
    load_yaml,
    parse_model,
    validate_project,
)
from floorplan_engine.wiring import (
    CHASE_CABLES,
    CHASE_NARROW,
    CHASE_SHARE,
    END_ALLOWANCE,
    HOLE_CABLES,
    RESERVE,
    Wiring,
    box_wiring,
)

OUT_DIR = "out"
PROJECT_FILE = "project.dxf"
ARTIFACT_FILE = "project.epd"
WIRING_JOURNAL_FILE = "wiring-boxes.csv"  # кабельный журнал проводки через коробки
CHASES_FILE = "wiring-chases.csv"  # ведомость штроб по стенам
SHEETS_DIR = "sheets"


class AuditError(RuntimeError):
    """Записанный DXF не прошёл аудит ezdxf."""


@dataclass
class Assessment:
    report: Report
    stages: list[StageResult]

    @property
    def name(self) -> str:
        return self.report.plan.name if self.report.plan else ""

    def status(self, stage: Stage) -> StageResult | None:
        return next((r for r in self.stages if r.stage is stage), None)

    @property
    def global_errors(self) -> list[Issue]:
        """Ошибки вне файлов этапов (intake.yaml, answers.yaml) — останавливают всё."""
        stage_files = set(STAGE_FILES.values())
        return [i for i in self.report.errors if i.file not in stage_files]

    @property
    def plan_builds(self) -> bool:
        plan = self.status(Stage.PLAN)
        return (
            not self.global_errors
            and self.report.plan is not None
            and plan is not None
            and plan.status.builds
        )

    @property
    def open_questions(self) -> int:
        return sum(len(r.open_questions) for r in self.stages)


@dataclass
class BuildResult:
    assessment: Assessment
    report_files: list[Path] = field(default_factory=list)
    dxf: Path | None = None
    artifact: Path | None = None
    journal: Path | None = None  # кабельный журнал проводки через коробки (CSV)
    chases: Path | None = None  # ведомость штроб (CSV)
    price_issues: list[Issue] = field(default_factory=list)  # prices.yaml не прочитан
    sheets: list[Path] = field(default_factory=list)

    @property
    def built(self) -> bool:
        return self.dxf is not None


def assess_project(project: Path) -> Assessment:
    report = validate_project(project)
    return Assessment(report, assess(report))


def write_report(out: Path, assessment: Assessment, fallback_name: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    name = assessment.name or fallback_name
    md, js = out / REPORT_MD, out / REPORT_JSON
    md.write_text(render_markdown(name, assessment.report, assessment.stages), encoding="utf-8")
    js.write_text(to_json(name, assessment.report, assessment.stages), encoding="utf-8")
    return [md, js]


def save_checked(doc: Drawing, path: Path) -> Drawing:
    """Сохранить DXF, перечитать и проверить аудитом ezdxf; вернуть перечитанный документ."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path, encoding="utf-8")
    reread = readfile(path)
    auditor = reread.audit()
    if auditor.has_errors:
        messages = "; ".join(err.message for err in auditor.errors)
        raise AuditError(f"аудит {path.name}: {messages}")
    return reread


def render_sheets(out: Path) -> list[Path]:
    """PNG каждого листа project.dxf в out/sheets/NN-<лист>.png, например 02-electrical.png
    (старые превью удаляются)."""
    dxf = out / PROJECT_FILE
    if not dxf.exists():
        return []
    sheets = out / SHEETS_DIR
    for old in sheets.glob("*.png"):
        old.unlink()
    doc = readfile(dxf)
    return [
        render_png(doc, layout, sheets / sheet_png_name(layout.name))
        for layout in sheet_layouts(doc)
    ]


def build_project(project: Path, previews: bool = False) -> BuildResult:
    """Оценить проект, записать отчёт и, если план можно строить, собрать DXF и артефакт .epd
    из этапов, которые можно строить. Листы показываются из .epd (canvas); PNG из DXF —
    только с previews=True, иначе старые out/sheets/*.png удаляются."""
    assessment = assess_project(project)
    out = project / OUT_DIR
    result = BuildResult(assessment, write_report(out, assessment, project.name))
    if not assessment.plan_builds:
        return result
    report = assessment.report
    assert report.plan is not None
    elec_status = assessment.status(Stage.ELECTRICAL)
    elec = report.electrical if elec_status is not None and elec_status.status.builds else None
    prices: PriceList | None = None
    if elec is not None and (project / PRICES_FILE).exists():
        prices, result.price_issues = load_prices(project / PRICES_FILE)
    edits = report.wiring_edits
    doc = build_project_document(report.plan, report.contours, elec, prices=prices, edits=edits)
    saved = save_checked(doc, out / PROJECT_FILE)
    result.dxf = out / PROJECT_FILE
    wiring: Wiring | None = None
    edit: dict[str, Any] | None = None
    scene: dict[str, Any] | None = None
    if elec is not None:
        # В масштабе листа: узлы подключения, трассы и полосы пучков — ровно как на чертеже
        with drawing_scale(document_scale(saved)):
            wiring = box_wiring(report.plan, report.contours, elec, edits)
            if wiring is not None:
                edit = wiring_handles(report.plan, report.contours, wiring)
                scene = build_scene(report.plan, report.contours, elec, wiring)
    journal, chases = out / WIRING_JOURNAL_FILE, out / CHASES_FILE
    if wiring is not None:
        assert elec is not None
        titles = wire_titles(report.plan, elec, wiring)
        result.journal = write_journal(wiring, journal, titles)
        result.chases = write_chases(wiring, chases)
        if wiring.edit_notes:
            report.issues += [
                Issue(WIRING_FILE, path, msg, Severity.WARNING) for path, msg in wiring.edit_notes
            ]
            result.report_files = write_report(out, assessment, project.name)
    else:
        journal.unlink(missing_ok=True)
        chases.unlink(missing_ok=True)
    # Артефакт — из записанного файла: ровно то, что откроет AutoCAD
    objects = describe_objects(report.plan, report.contours, elec, wiring)
    tables = side_tables(report.plan, report.contours, elec, wiring, prices)
    chains = line_chains(wiring) if wiring is not None else None
    groups = line_groups(wiring) if wiring is not None else None
    result.artifact = export_artifact(
        saved, report.plan, out / ARTIFACT_FILE, objects, tables, chains, groups, edit, scene
    )
    if previews:
        result.sheets = render_sheets(out)
    else:
        for old in (out / SHEETS_DIR).glob("*.png"):
            old.unlink()
    return result


def save_wiring_edits(project: Path, changes: dict[str, Any]) -> list[Issue]:
    """Правки проводки из просмотра — в wiring.yaml проекта: changes = {"wires": {id: правка
    или None}, "boxes": {...}}; None убирает правку (линия — снова автотрасса). Пустые правки —
    файла нет. Ошибки — с путём к полю, файл тогда не меняется."""
    path = project / WIRING_FILE
    data: dict[str, Any] = {"wires": {}, "boxes": {}}
    if path.exists():
        raw, issues = load_yaml(path)
        if issues and raw is None and path.stat().st_size:
            return issues
        if isinstance(raw, dict):
            data.update({k: dict(raw.get(k) or {}) for k in ("wires", "boxes")})
    for kind in ("wires", "boxes"):
        for key, value in (changes.get(kind) or {}).items():
            if value is None:
                data[kind].pop(key, None)
            else:
                data[kind][key] = value
    edits, issues = parse_model(WiringEdits, data, WIRING_FILE)
    if edits is None:
        return issues
    if not edits.wires and not edits.boxes:
        path.unlink(missing_ok=True)
        return []
    path.write_text(dump_wiring_edits(edits), encoding="utf-8")
    return []


def dump_wiring_edits(edits: WiringEdits) -> str:
    """wiring.yaml: по строке на коробку и на линию, точки трассы — в одну строку."""

    def xy(p: tuple[float, float]) -> str:
        return f"[{p[0]:g}, {p[1]:g}]"

    def q(text: str) -> str:  # строка JSON — это и строка YAML, с любыми символами
        return json.dumps(text, ensure_ascii=False)

    lines = [
        "# Ручные правки проводки из просмотра (floorplan-engine view), мм модели.",
        "# Остальное строится автоматически; удалить запись — вернуть автотрассу.",
    ]
    if edits.boxes:
        lines.append("boxes:")
        for bid, b in sorted(edits.boxes.items()):
            lines.append(
                f"  {q(bid)}: {{ room: {q(b.room)}, group: {q(b.group)}, at: {xy(b.at)} }}"
            )
    if edits.wires:
        lines.append("wires:")
        for wid, w in sorted(edits.wires.items(), key=lambda kv: _natural(kv[0])):
            path = ", ".join(xy(p) for p in w.path)
            lines.append(f"  {q(wid)}: {{ from: {q(w.from_)}, to: {q(w.to)}, path: [{path}] }}")
    return "\n".join(lines) + "\n"


def _natural(key: str) -> tuple[str, int]:
    """wire_2 раньше wire_10."""
    head, _, tail = key.rpartition("_")
    return (head, int(tail)) if tail.isdigit() else (key, 0)


@dataclass
class EstimateResult:
    assessment: Assessment
    issues: list[Issue] = field(default_factory=list)  # ошибки прайса и причины, почему сметы нет
    estimate: Estimate | None = None
    prices: Path | None = None  # прайс, по которому считали (None — без цен)
    files: list[Path] = field(default_factory=list)


def load_prices(path: Path) -> tuple[PriceList | None, list[Issue]]:
    """Прайс проекта; ошибки — с путём к полю, неизвестный ключ позиции — тоже ошибка."""
    data, issues = load_yaml(path)
    if data is None:
        return None, issues
    prices, issues = parse_model(PriceList, data, path.name)
    if prices is None:
        return None, issues
    bad = [Issue(path.name, f"items.{k}", "нет такой позиции сметы") for k in unknown_keys(prices)]
    return (None, bad) if bad else (prices, [])


def estimate_project(project: Path, prices_path: Path | None = None) -> EstimateResult:
    """Смета электрики: объёмы из модели, цены — из prices.yaml проекта (или prices_path).
    Нет прайса — смета с объёмами без цен. Пишет out/estimate.md и estimate.csv."""
    assessment = assess_project(project)
    result = EstimateResult(assessment)
    report = assessment.report
    elec_status = assessment.status(Stage.ELECTRICAL)
    if not assessment.plan_builds or elec_status is None or not elec_status.status.builds:
        result.issues.append(Issue("electrical.yaml", "", "этап электрики не строится — см. check"))
        return result
    assert report.plan is not None and report.electrical is not None
    wiring = box_wiring(report.plan, report.contours, report.electrical, report.wiring_edits)
    if wiring is None:
        result.issues.append(Issue("electrical.yaml", "board", "нет щита или точек с группами"))
        return result
    path = prices_path or project / PRICES_FILE
    prices = PriceList()
    if path.exists():
        loaded, issues = load_prices(path)
        if loaded is None:
            result.issues += issues
            return result
        prices, result.prices = loaded, path
    language = report.plan.language
    est = build_estimate(wiring, report.electrical, prices, language)
    result.estimate = est
    notes = _estimate_notes(assessment, wiring, report.electrical, prices, result.prices)
    title = estimate_text("title", language, name=report.plan.name)
    out = project / OUT_DIR
    result.files = [
        write_markdown(est, out / ESTIMATE_MD, title, notes, language),
        write_csv(est, out / ESTIMATE_CSV),
    ]
    return result


def _estimate_notes(
    assessment: Assessment,
    wiring: Wiring,
    elec: Electrical,
    prices: PriceList,
    source: Path | None,
) -> list[str]:
    """Откуда цены, какие допущения в объёмах и что в смету не входит."""
    assert assessment.report.plan is not None
    lang = assessment.report.plan.language
    if source is not None:
        date = f" ({prices.date})" if prices.date else ""
        note = f" — {prices.note}" if prices.note else ""
        notes = [estimate_text("note_prices", lang, f=source.name, date=date, note=note)]
    else:
        notes = [estimate_text("note_no_prices", lang, f=PRICES_FILE)]
    notes += [
        estimate_text("note_cable", lang, pct=round(RESERVE * 100)),
        estimate_text("note_chases", lang, d=f"{CHASE_SHARE:g}", k=CHASE_CABLES, n=CHASE_NARROW),
        estimate_text("note_holes", lang, k=HOLE_CABLES),
        estimate_text("note_fixing", lang, step=f"{FIXING_STEP:g}"),
        estimate_text("note_crimp", lang),
    ]
    if elec.board is not None:
        notes.append(
            estimate_text(
                "note_board_tail", lang, h=f"{elec.board.height:g}", e=f"{END_ALLOWANCE:g}"
            )
        )
    with_boxes = {b.group for b in wiring.boxes}
    direct = sorted({r.group for r in wiring.runs} - with_boxes, key=group_key)
    if direct:
        notes.append(estimate_text("note_direct", lang, groups=", ".join(direct)))
    wet = sum(1 for b in wiring.boxes if b.wet)
    if wet:
        notes.append(estimate_text("note_wet", lang, n=wet))
    notes.append(estimate_text("note_excluded", lang))
    if wiring.height_assumed:
        notes.append(estimate_text("note_height", lang))
    status = assessment.status(Stage.ELECTRICAL)
    if status is not None and status.open_questions:
        ids = ", ".join(q.id for q in status.open_questions)
        notes.append(estimate_text("note_questions", lang, ids=ids))
    return notes
