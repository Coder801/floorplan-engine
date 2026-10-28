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
from floorplan_engine.draw_electrical import group_colors, group_key
from floorplan_engine.draw_wiring import write_chases, write_journal
from floorplan_engine.estimate import (
    ESTIMATE_CSV,
    ESTIMATE_MD,
    ESTIMATE_XLSX,
    FIXING_STEP,
    PRICES_FILE,
    Estimate,
    PriceList,
    build_estimate,
    unknown_keys,
    write_csv,
    write_markdown,
    write_xlsx,
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
from floorplan_engine.panel import build_panel, panel_data, write_loads
from floorplan_engine.preview import paper_size, render_png, sheet_layouts
from floorplan_engine.printing import SheetCheck, check_sheets, write_album
from floorplan_engine.report import REPORT_JSON, REPORT_MD, render_markdown, to_json
from floorplan_engine.scene3d import build_scene
from floorplan_engine.schema import Electrical, SheetFormat, WiringEdits
from floorplan_engine.sheets import build_project_document, document_scale, sheet_png_name
from floorplan_engine.side import side_tables
from floorplan_engine.thumbnail import PREVIEW_FILE, plan_thumbnail
from floorplan_engine.titleblock import FORMATS
from floorplan_engine.validate import (
    ELECTRICAL_FILE,
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
    estimate_wiring,
)

OUT_DIR = "out"
PROJECT_FILE = "project.dxf"
ARTIFACT_FILE = "project.epd"
ALBUM_FILE = "album.pdf"  # PDF-альбом листов (команда print)
WIRING_JOURNAL_FILE = "wiring-boxes.csv"  # кабельный журнал проводки через коробки
CHASES_FILE = "wiring-chases.csv"  # ведомость штроб по стенам
LOADS_FILE = "panel-loads.csv"  # роспись потребителей по группам щита
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
    loads: Path | None = None  # роспись потребителей щита (CSV)
    price_issues: list[Issue] = field(default_factory=list)  # prices.yaml не прочитан
    sheets: list[Path] = field(default_factory=list)

    @property
    def built(self) -> bool:
        return self.dxf is not None


def assess_project(project: Path) -> Assessment:
    report = validate_project(project)
    return Assessment(report, assess(report))


def _sheet_inputs(
    project: Path, assessment: Assessment
) -> tuple[Electrical | None, PriceList | None, list[Issue]]:
    """Что идёт на листы, кроме плана: электрика (если этап строится) и прайс сметы."""
    report = assessment.report
    elec_status = assessment.status(Stage.ELECTRICAL)
    elec = report.electrical if elec_status is not None and elec_status.status.builds else None
    price_path = find_prices(project)
    if elec is None or price_path is None:
        return elec, None, []
    prices, issues = load_prices(price_path)
    return elec, prices, issues


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
    elec, prices, result.price_issues = _sheet_inputs(project, assessment)
    edits = report.wiring_edits
    doc = build_project_document(report.plan, report.contours, elec, prices=prices, edits=edits)
    saved = save_checked(doc, out / PROJECT_FILE)
    result.dxf = out / PROJECT_FILE
    # Превью для карточки проекта в просмотре
    (out / PREVIEW_FILE).write_text(plan_thumbnail(report.plan, report.contours), "utf-8")
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
    panel = build_panel(report.plan, elec) if elec is not None else None
    loads = out / LOADS_FILE
    if panel is not None:
        result.loads = write_loads(panel, loads)
        if panel.warnings:
            report.issues += [
                Issue(
                    ELECTRICAL_FILE,
                    f"groups.{w.group}" if w.group else "panel",
                    w.text["ru"],
                    Severity.WARNING,
                )
                for w in panel.warnings
            ]
            result.report_files = write_report(out, assessment, project.name)
    else:
        loads.unlink(missing_ok=True)
    panel_view = None
    if panel is not None:
        assert elec is not None
        board = elec.board.name if elec.board is not None else "ЩР"
        panel_view = panel_data(panel, group_colors(elec), board, report.plan.language)
    # Артефакт — из записанного файла: ровно то, что откроет AutoCAD
    objects = describe_objects(report.plan, report.contours, elec, wiring)
    quantities = None
    if wiring is not None and elec is not None:
        quantities = estimate_wiring(report.plan, report.contours, elec, edits)
    tables = side_tables(report.plan, report.contours, elec, wiring, prices, quantities)
    chains = line_chains(wiring) if wiring is not None else None
    groups = line_groups(wiring) if wiring is not None else None
    result.artifact = export_artifact(
        saved,
        report.plan,
        out / ARTIFACT_FILE,
        objects,
        tables,
        chains,
        groups,
        edit,
        scene,
        panel_view,
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


@dataclass
class PrintResult:
    assessment: Assessment
    issues: list[Issue] = field(default_factory=list)  # почему альбома нет
    pdf: Path | None = None
    dxf: Path | None = None  # DXF под заданный формат (свой формат — out/project.dxf)
    paper: str = ""  # «A3»
    scale: float = 0.0  # 50 — это 1:50
    checks: list[SheetCheck] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [w for c in self.checks for w in c.warnings()]


def print_project(project: Path, paper: SheetFormat = "auto") -> PrintResult:
    """PDF-альбом листов в натуральную величину (printing.py). paper="auto" — комплект как
    при сборке (out/project.dxf → out/album.pdf; сборки нет — ошибка); заданный формат —
    листы раскладываются заново под него: out/print-A3.dxf и out/album-A3.pdf."""
    assessment = assess_project(project)
    result = PrintResult(assessment)
    out = project / OUT_DIR
    plan = assessment.report.plan
    if paper == "auto":
        dxf = out / PROJECT_FILE
        if not dxf.exists():
            result.issues.append(Issue(PROJECT_FILE, "", "нет сборки — сначала build"))
            return result
        doc, pdf = readfile(dxf), out / ALBUM_FILE
    else:
        if not assessment.plan_builds or plan is None:
            result.issues.append(Issue("room.yaml", "", "план не строится — см. check"))
            return result
        elec, prices, result.issues = _sheet_inputs(project, assessment)
        sheet = plan.sheet.model_copy(update={"format": paper})
        doc = build_project_document(
            plan.model_copy(update={"sheet": sheet}),
            assessment.report.contours,
            elec,
            prices=prices,
            edits=assessment.report.wiring_edits,
        )
        result.dxf = out / f"print-{paper}.dxf"
        doc = save_checked(doc, result.dxf)
        pdf = out / f"album-{paper}.pdf"
    layouts = sheet_layouts(doc)
    if layouts:
        size = sorted(paper_size(layouts[0]))
        result.paper = next((n for n, f in FORMATS.items() if list(f) == size), "")
    result.scale = document_scale(doc)
    result.checks = check_sheets(doc)
    title = plan.name if plan is not None else project.name
    result.pdf = write_album(doc, pdf, title)
    return result


def find_prices(project: Path) -> Path | None:
    """Прайс сметы: свой у проекта (prices.yaml в его папке), иначе — общий прайс студии
    (prices.yaml в папке над проектами, рядом со studio.yaml); нет ни того, ни другого — None."""
    for path in (project / PRICES_FILE, project.parent / PRICES_FILE):
        if path.is_file():
            return path
    return None


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
    """Смета электрики: объёмы из модели, цены — из prices.yaml проекта, иначе из общего
    прайса студии (find_prices), или из prices_path. Нет прайса — смета с объёмами без цен.
    Пишет out/estimate.md, estimate.csv и estimate.xlsx."""
    assessment = assess_project(project)
    result = EstimateResult(assessment)
    report = assessment.report
    elec_status = assessment.status(Stage.ELECTRICAL)
    if not assessment.plan_builds or elec_status is None or not elec_status.status.builds:
        result.issues.append(Issue("electrical.yaml", "", "этап электрики не строится — см. check"))
        return result
    assert report.plan is not None and report.electrical is not None
    wiring = estimate_wiring(report.plan, report.contours, report.electrical, report.wiring_edits)
    if wiring is None:
        result.issues.append(Issue("electrical.yaml", "board", "нет щита или точек с группами"))
        return result
    path = prices_path or find_prices(project)
    prices = PriceList()
    if path is not None and path.exists():
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
        write_xlsx(est, out / ESTIMATE_XLSX, title, notes, language),
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
