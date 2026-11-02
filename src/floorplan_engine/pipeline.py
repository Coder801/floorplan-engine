"""Конвейер проекта без вывода на экран: оценка, отчёт, сборка DXF, артефакта и PNG.

Общий для CLI и сервиса: CLI печатает результат, сервис кладёт его в состояние проекта.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from ezdxf.document import Drawing
from ezdxf.filemanagement import readfile

from floorplan_engine.drawing.titleblock import FORMATS
from floorplan_engine.drawing.wiring import write_chases, write_journal
from floorplan_engine.electrical.chases import CHASE_CABLES, CHASE_SHARE, HOLE_CABLES
from floorplan_engine.electrical.elevations import elevation_data
from floorplan_engine.electrical.estimate import (
    ESTIMATE_CSV,
    ESTIMATE_MD,
    ESTIMATE_XLSX,
    FIXING_STEP,
    PRICES_FILE,
    Estimate,
    PriceList,
    PriceSource,
    build_estimate,
    unknown_keys,
    write_csv,
    write_markdown,
    write_xlsx,
)
from floorplan_engine.electrical.estimate import text as estimate_text
from floorplan_engine.electrical.groups import group_colors, group_key
from floorplan_engine.electrical.panel import BoardPanel, build_panel, write_loads
from floorplan_engine.electrical.pricing import MockPriceService, Prices, price_notes
from floorplan_engine.electrical.variants import all_variants, variant_summary
from floorplan_engine.electrical.wiring import END_ALLOWANCE, RESERVE, box_wiring, estimate_wiring
from floorplan_engine.electrical.wiring_model import CHASE_NARROW, Wiring
from floorplan_engine.epd.artifact import export_artifact
from floorplan_engine.epd.objects import (
    describe_objects,
    line_chains,
    line_groups,
    wire_titles,
    wiring_handles,
)
from floorplan_engine.epd.overview import overview_data
from floorplan_engine.epd.panel_data import panel_data
from floorplan_engine.epd.plumbing import plumbing_objects, plumbing_scene, plumbing_tables
from floorplan_engine.epd.scene3d import build_scene
from floorplan_engine.epd.side import side_legends, side_tables
from floorplan_engine.epd.thumbnail import PREVIEW_FILE, plan_thumbnail
from floorplan_engine.model.intake import Stage
from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.model.plumbing import PLUMBING_FILE, Plumbing
from floorplan_engine.model.scale import drawing_scale
from floorplan_engine.model.schema import Electrical, SheetFormat, Variant, WiringEdits, WiringFile
from floorplan_engine.plumbing.estimate import LINES as PLUMBING_LINES
from floorplan_engine.plumbing.estimate import MOCK_PRICES as PLUMBING_MOCK_PRICES
from floorplan_engine.plumbing.estimate import RESERVE as PLUMBING_RESERVE
from floorplan_engine.plumbing.estimate import build_estimate as build_plumbing_estimate
from floorplan_engine.plumbing.estimate import text as plumbing_estimate_text
from floorplan_engine.plumbing.network import Network, build_network, routes_json
from floorplan_engine.plumbing.rows import water_views
from floorplan_engine.sheets.document import build_project_document, document_scale, sheet_png_name
from floorplan_engine.sheets.preview import paper_size, render_png, sheet_layouts
from floorplan_engine.sheets.printing import SheetCheck, check_sheets, write_album
from floorplan_engine.validation.answers import load_optional
from floorplan_engine.validation.assess import STAGE_FILES, StageResult, assess
from floorplan_engine.validation.issues import (
    ELECTRICAL_FILE,
    VARIANT_FILE,
    WIRING_FILE,
    Issue,
    Severity,
    load_yaml,
    parse_model,
)
from floorplan_engine.validation.report import REPORT_JSON, REPORT_MD, render_markdown, to_json
from floorplan_engine.validation.validate import Report, validate_project

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
    estimate: list[Path] = field(default_factory=list)  # смета: md, csv, xlsx — как на листе
    plumbing_estimate: list[Path] = field(default_factory=list)  # смета сантехники
    sewer_routes: Path | None = None  # трассы канализации (JSON, формат ТЗ трассировки)
    price_issues: list[Issue] = field(default_factory=list)  # prices.yaml не прочитан
    sheets: list[Path] = field(default_factory=list)

    @property
    def built(self) -> bool:
        return self.dxf is not None


def assess_project(project: Path) -> Assessment:
    report = validate_project(project)
    return Assessment(report, assess(report))


def _sheet_inputs(
    project: Path, assessment: Assessment, service: PriceSource | None
) -> tuple[Electrical | None, Prices | None, list[Issue]]:
    """Что идёт на листы, кроме плана: электрика (если этап строится) и цены смет — прайс
    проекта или студии (если есть и читается) поверх сервиса цен; цены нужны и без электрики,
    если строится сантехника."""
    report = assessment.report
    elec_status = assessment.status(Stage.ELECTRICAL)
    elec = report.electrical if elec_status is not None and elec_status.status.builds else None
    if elec is None and plumbing_of(assessment) is None:
        return None, None, []
    price_path = find_prices(project)
    own, issues = load_prices(price_path) if price_path is not None else (None, [])
    return elec, Prices(own, service), issues


def plumbing_of(assessment: Assessment) -> Plumbing | None:
    """Сантехника, если её этап строится (plumbing.yaml без ошибок, вопросы не мешают)."""
    status = assessment.status(Stage.PLUMBING)
    if status is None or not status.status.builds:
        return None
    return assessment.report.plumbing


def price_service(given: PriceSource | None) -> PriceSource:
    """Сервис цен для смет: переданный клиент (service/, позже) или имитация — она знает и
    позиции сантехники (plumbing/estimate.MOCK_PRICES)."""
    return given if given is not None else MockPriceService(extra=PLUMBING_MOCK_PRICES)


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


def build_project(
    project: Path, previews: bool = False, prices_from: PriceSource | None = None
) -> BuildResult:
    """Оценить проект, записать отчёт и, если план можно строить, собрать DXF и артефакт .epd
    из этапов, которые можно строить. Листы показываются из .epd (canvas); PNG из DXF —
    только с previews=True, иначе старые out/sheets/*.png удаляются. prices_from — сервис
    цен для сметы; None — имитация (pricing.MockPriceService)."""
    assessment = assess_project(project)
    out = project / OUT_DIR
    result = BuildResult(assessment, write_report(out, assessment, project.name))
    if not assessment.plan_builds:
        return result
    report = assessment.report
    assert report.plan is not None
    elec, prices, result.price_issues = _sheet_inputs(
        project, assessment, price_service(prices_from)
    )
    edits = report.wiring_edits
    plumbing = plumbing_of(assessment)
    doc = build_project_document(
        report.plan, report.contours, elec, prices=prices, edits=edits, plumbing=plumbing
    )
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
    net = build_network(report.plan, report.contours, plumbing) if plumbing is not None else None
    if net is not None and net.weak:
        report.issues += [
            Issue(
                PLUMBING_FILE, w.target and f"fixtures.{w.target}", w.text["ru"], Severity.WARNING
            )
            for w in net.weak
        ]
        result.report_files = write_report(out, assessment, project.name)
    routes = out / SEWER_ROUTES_FILE
    if net is not None and plumbing is not None:
        result.plumbing_estimate = write_plumbing_estimate(
            project, assessment, net, plumbing, prices or Prices(), find_prices(project)
        )
        routes.write_text(
            json.dumps(routes_json(net), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        result.sewer_routes = routes
    else:
        for name in PLUMBING_ESTIMATE_FILES:
            (out / name).unlink(missing_ok=True)
        routes.unlink(missing_ok=True)
    panel_view = None
    if panel is not None:
        assert elec is not None
        board = elec.board.name if elec.board is not None else "ЩР"
        panel_view = panel_data(panel, group_colors(elec), board, report.plan.language)
    # Артефакт — из записанного файла: ровно то, что откроет AutoCAD
    water = water_views(plumbing, net) if plumbing is not None and net is not None else None
    objects = describe_objects(report.plan, report.contours, elec, wiring, water)
    if net is not None and plumbing is not None:
        objects |= plumbing_objects(report.plan, plumbing, net)
    quantities = None
    if wiring is not None and elec is not None:
        quantities = estimate_wiring(report.plan, report.contours, elec, edits)
    tables = side_tables(report.plan, report.contours, elec, wiring, prices, quantities)
    if net is not None and plumbing is not None:
        tables |= plumbing_tables(report.plan, plumbing, net, prices)
        if scene is not None:
            ceiling = wiring.ceiling_height if wiring is not None else report.plan.ceiling_height
            scene |= plumbing_scene(net, ceiling)
    if quantities is not None and elec is not None and not result.price_issues:
        # Смета файлами — та же, что на листе: Excel в просмотре не отстаёт от листов;
        # прайс с ошибкой — смету не пишем (ошибки — в price_issues), старую убираем
        _, result.estimate = write_estimate(
            project,
            assessment,
            quantities,
            elec,
            prices or Prices(),
            find_prices(project),
            panel,
        )
    else:
        for name in (ESTIMATE_MD, ESTIMATE_CSV, ESTIMATE_XLSX):
            (out / name).unlink(missing_ok=True)
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
        elevation_data(
            report.plan,
            report.contours,
            elec,
            wiring,
            group_colors(elec),
            water,
        )
        if elec is not None
        else None,
        side_legends(elec, report.plan.language) if elec is not None else None,
        variant_block(report, prices) if elec is not None and prices is not None else None,
        overview_data(
            report.plan,
            report.contours,
            elec,
            panel,
            plumbing,
            net,
            build_plumbing_estimate(net, plumbing, prices or Prices(), report.plan.language)
            if net is not None and plumbing is not None
            else None,
        ),
    )
    if previews:
        result.sheets = render_sheets(out)
    else:
        for old in (out / SHEETS_DIR).glob("*.png"):
            old.unlink()
    return result


def variant_block(report: Report, prices: Prices) -> dict[str, Any] | None:
    """Варианты проводки для просмотра (манифест .epd, ключ variants): выбранный, «как в
    проекте» и сводка каждого — смета, кабель, аппараты, штробы — без чертежей."""
    source, chosen, default = report.source_electrical, report.variant, report.default_variant
    if report.plan is None or source is None or chosen is None or default is None:
        return None
    wiring_file = report.wiring_file or WiringFile()
    items = []
    for variant in all_variants():
        edits = wiring_file.edits_for(variant.key, default.key)
        summary = variant_summary(report.plan, report.contours, source, variant, edits, prices)
        if summary is not None:
            items.append(summary.as_dict())
    return {"active": chosen.key, "default": default.key, "items": items}


def save_variant(project: Path, data: dict[str, Any]) -> list[Issue]:
    """Вариант проводки из просмотра — в variant.yaml: {mode, route, distribution, ceiling_height?}.
    Нет ceiling_height — прежняя высота остаётся. Ошибки —
    с путём к полю, файл тогда не меняется."""
    path = project / VARIANT_FILE
    if "ceiling_height" not in data:  # смена варианта не сбрасывает высоту потолка
        old, _ = load_optional(path, Variant)
        if old is not None and old.ceiling_height is not None:
            data = {**data, "ceiling_height": old.ceiling_height}
    variant, issues = parse_model(Variant, data, VARIANT_FILE)
    if variant is None:
        return issues
    path.write_text(
        "# Вариант проводки и высота потолка, выбранные в просмотре (docs/wiring-variants.md).\n"
        + yaml.safe_dump(
            variant.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False
        ),
        encoding="utf-8",
    )
    return []


def save_wiring_edits(project: Path, changes: dict[str, Any]) -> list[Issue]:
    """Правки проводки из просмотра — в wiring.yaml проекта, в раздел выбранного варианта
    (variants.<ключ>): changes = {"wires": {id: правка или None}, "boxes": {...}}; None
    убирает правку (линия — снова автотрасса). Правки до вариантов (wires и boxes верхнего
    уровня) при правке варианта «как в проекте» переезжают в его раздел. Нет правок — нет
    файла. Ошибки — с путём к полю, файл тогда не меняется."""
    path = project / WIRING_FILE
    report = validate_project(project)
    # Электрика не читается — варианта нет: правки — по-старому, вне разделов вариантов
    key = report.variant.key if report.variant is not None else None
    default_key = report.default_variant.key if report.default_variant is not None else None
    current = WiringFile()
    if path.exists():
        raw, issues = load_yaml(path)
        if issues and raw is None and path.stat().st_size:
            return issues
        if isinstance(raw, dict):
            parsed, issues = parse_model(WiringFile, raw, WIRING_FILE)
            if parsed is None:
                return issues
            current = parsed
    if key is None or default_key is None:
        edits = WiringEdits(wires=current.wires, boxes=current.boxes)
    else:
        edits = current.edits_for(key, default_key) or WiringEdits()
    data: dict[str, Any] = {
        "wires": {k: v.model_dump(by_alias=True) for k, v in edits.wires.items()},
        "boxes": {k: v.model_dump() for k, v in edits.boxes.items()},
    }
    for kind in ("wires", "boxes"):
        for name, value in (changes.get(kind) or {}).items():
            if value is None:
                data[kind].pop(name, None)
            else:
                data[kind][name] = value
    new, issues = parse_model(WiringEdits, data, WIRING_FILE)
    if new is None:
        return issues
    variants = dict(current.variants)
    if key is None:
        result = WiringFile(wires=new.wires, boxes=new.boxes, variants=variants)
    else:
        variants[key] = new
        keep_legacy = key != default_key  # правки до вариантов — у варианта «как в проекте»
        result = WiringFile(
            wires=current.wires if keep_legacy else {},
            boxes=current.boxes if keep_legacy else {},
            variants={k: v for k, v in variants.items() if v.wires or v.boxes},
        )
    if not (result.wires or result.boxes or result.variants):
        path.unlink(missing_ok=True)
        return []
    path.write_text(dump_wiring_file(result), encoding="utf-8")
    return []


def dump_wiring_file(data: WiringFile) -> str:
    """wiring.yaml с вариантами: правки до вариантов (если остались), затем variants."""
    head = [
        "# Ручные правки проводки из просмотра (floorplan-engine view), мм модели, по вариантам",
        "# проводки (variants.<режим-трасса-разводка>). Удалить запись — вернуть автотрассу.",
    ]
    body: list[str] = []
    legacy = WiringEdits(wires=data.wires, boxes=data.boxes)
    if legacy.wires or legacy.boxes:
        body += _edit_lines(legacy, "")
    if data.variants:
        body.append("variants:")
        for key in sorted(data.variants):
            body.append(f"  {json.dumps(key)}:")
            body += _edit_lines(data.variants[key], "    ")
    return "\n".join(head + body) + "\n"


def dump_wiring_edits(edits: WiringEdits) -> str:
    """Правки одного варианта (wiring.yaml до вариантов): по строке на коробку и на линию."""
    head = [
        "# Ручные правки проводки из просмотра (floorplan-engine view), мм модели.",
        "# Остальное строится автоматически; удалить запись — вернуть автотрассу.",
    ]
    return "\n".join(head + _edit_lines(edits, "")) + "\n"


def _edit_lines(edits: WiringEdits, indent: str) -> list[str]:
    """Строки правок с отступом: по строке на коробку и на линию, точки трассы — в одну строку."""

    def xy(p: tuple[float, float]) -> str:
        return f"[{p[0]:g}, {p[1]:g}]"

    def q(text: str) -> str:  # строка JSON — это и строка YAML, с любыми символами
        return json.dumps(text, ensure_ascii=False)

    lines = []
    if edits.boxes:
        lines.append(f"{indent}boxes:")
        for bid, b in sorted(edits.boxes.items()):
            lines.append(
                f"{indent}  {q(bid)}: {{ room: {q(b.room)}, group: {q(b.group)}, at: {xy(b.at)} }}"
            )
    if edits.wires:
        lines.append(f"{indent}wires:")
        for wid, w in sorted(edits.wires.items(), key=lambda kv: _natural(kv[0])):
            path = ", ".join(xy(p) for p in w.path)
            lines.append(
                f"{indent}  {q(wid)}: {{ from: {q(w.from_)}, to: {q(w.to)}, path: [{path}] }}"
            )
    return lines


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


def print_project(
    project: Path, paper: SheetFormat = "auto", prices_from: PriceSource | None = None
) -> PrintResult:
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
        elec, prices, result.issues = _sheet_inputs(project, assessment, price_service(prices_from))
        sheet = plan.sheet.model_copy(update={"format": paper})
        doc = build_project_document(
            plan.model_copy(update={"sheet": sheet}),
            assessment.report.contours,
            elec,
            prices=prices,
            edits=assessment.report.wiring_edits,
            plumbing=plumbing_of(assessment),
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


SEWER_ROUTES_FILE = "sewer-routes.json"  # трассы канализации: участки, зоны, высоты, ошибки
PLUMBING_ESTIMATE_FILES = (
    "plumbing-estimate.md",
    "plumbing-estimate.csv",
    "plumbing-estimate.xlsx",
)


def write_plumbing_estimate(
    project: Path,
    assessment: Assessment,
    net: Network,
    plumbing: Plumbing,
    prices: Prices,
    source: Path | None,
) -> list[Path]:
    """Смета сантехники в out/: plumbing-estimate.md, .csv и .xlsx — та же, что на листе
    «Сантехника». Пишет build."""
    plan = assessment.report.plan
    assert plan is not None
    lang = plan.language
    est = build_plumbing_estimate(net, plumbing, prices, lang)
    if prices.priced:
        notes = price_notes(est, prices, lang, f=source.name if source else PRICES_FILE, note=True)
    else:
        notes = [estimate_text("note_no_prices", lang, f=PRICES_FILE)]
    notes += [
        plumbing_estimate_text("note_pipes", lang, pct=round(PLUMBING_RESERVE * 100)),
        plumbing_estimate_text("note_input", lang),
        plumbing_estimate_text("note_excluded", lang),
    ]
    status = assessment.status(Stage.PLUMBING)
    if status is not None and status.open_questions:
        ids = ", ".join(q.id for q in status.open_questions)
        notes.append(plumbing_estimate_text("note_questions", lang, ids=ids))
    title = plumbing_estimate_text("title", lang, name=plan.name)
    out = project / OUT_DIR
    md, csv_, xlsx = (out / name for name in PLUMBING_ESTIMATE_FILES)
    return [
        write_markdown(est, md, title, notes, lang),
        write_csv(est, csv_),
        write_xlsx(est, xlsx, title, notes, lang),
    ]


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
    keys = [k for k in unknown_keys(prices) if k not in PLUMBING_LINES]
    bad = [Issue(path.name, f"items.{k}", "нет такой позиции сметы") for k in keys]
    return (None, bad) if bad else (prices, [])


def estimate_project(
    project: Path, prices_path: Path | None = None, prices_from: PriceSource | None = None
) -> EstimateResult:
    """Смета электрики: объёмы из модели, цены — из prices.yaml проекта, иначе из общего
    прайса студии (find_prices), или из prices_path, поверх сервиса цен (prices_from; None —
    имитация). Пишет out/estimate.md, estimate.csv и estimate.xlsx."""
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
    own: PriceList | None = None
    if path is not None and path.exists():
        own, issues = load_prices(path)
        if own is None:
            result.issues += issues
            return result
        result.prices = path
    prices = Prices(own, price_service(prices_from))
    panel = build_panel(report.plan, report.electrical)
    result.estimate, result.files = write_estimate(
        project, assessment, wiring, report.electrical, prices, result.prices, panel
    )
    return result


def write_estimate(
    project: Path,
    assessment: Assessment,
    wiring: Wiring,
    elec: Electrical,
    prices: Prices,
    source: Path | None,
    panel: BoardPanel | None,
) -> tuple[Estimate, list[Path]]:
    """Смета в out/: estimate.md, .csv и .xlsx (формулы) — из тех же объёмов, что на листе
    проводки; щит — по составу листа «Щит» (panel). Пишут и estimate, и build."""
    assert assessment.report.plan is not None
    plan = assessment.report.plan
    est = build_estimate(wiring, elec, prices, plan.language, panel)
    notes = _estimate_notes(assessment, est, wiring, elec, prices, source)
    title = estimate_text("title", plan.language, name=plan.name)
    out = project / OUT_DIR
    files = [
        write_markdown(est, out / ESTIMATE_MD, title, notes, plan.language),
        write_csv(est, out / ESTIMATE_CSV),
        write_xlsx(est, out / ESTIMATE_XLSX, title, notes, plan.language),
    ]
    return est, files


def _estimate_notes(
    assessment: Assessment,
    est: Estimate,
    wiring: Wiring,
    elec: Electrical,
    prices: Prices,
    source: Path | None,
) -> list[str]:
    """Откуда цены, какие допущения в объёмах и что в смету не входит."""
    assert assessment.report.plan is not None
    lang = assessment.report.plan.language
    if prices.priced:
        notes = price_notes(est, prices, lang, f=source.name if source else PRICES_FILE, note=True)
    else:
        notes = [estimate_text("note_no_prices", lang, f=PRICES_FILE)]
    notes += [
        estimate_text("note_cable", lang, pct=round(RESERVE * 100)),
        estimate_text("note_chases", lang, d=f"{CHASE_SHARE:g}", k=CHASE_CABLES, n=CHASE_NARROW),
        estimate_text("note_holes", lang, k=HOLE_CABLES),
        estimate_text("note_fixing", lang, step=f"{FIXING_STEP:g}"),
        estimate_text("note_crimp", lang),
    ]
    if any(ln.key.startswith("conduit.") for ln in est.lines):
        notes.append(estimate_text("note_conduit", lang))
    if elec.board is not None:
        notes.append(estimate_text("note_panel", lang))
        notes.append(
            estimate_text(
                "note_board_tail", lang, h=f"{elec.board.height:g}", e=f"{END_ALLOWANCE:g}"
            )
        )
    if prices.own is not None and prices.own.board_kit and source is not None:
        keys = ", ".join(k.value for k in DeviceKind)
        notes.append(estimate_text("note_board_kit", lang, f=source.name, keys=keys))
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
