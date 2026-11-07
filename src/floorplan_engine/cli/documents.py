"""Commands over a project folder: check, build, print, previews, estimate; the core, no service."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from floorplan_engine.cli.common import ProjectArg, exit_on, fail, print_report, print_stages
from floorplan_engine.drawing.symbols import export_symbols
from floorplan_engine.epd.artifact import read_artifact, render_page_png
from floorplan_engine.model.schema import SheetFormat
from floorplan_engine.pipeline import (
    ARTIFACT_FILE,
    OUT_DIR,
    PROJECT_FILE,
    AuditError,
    assess_project,
    build_project,
    estimate_project,
    print_project,
    render_sheets,
)
from floorplan_engine.sheets.document import sheet_png_name

ARTIFACT_PREVIEW_DIR = "artifact"


def check(project: ProjectArg) -> None:
    """Проверить проект без отрисовки: ошибки данных и статус каждого этапа."""
    assessment = assess_project(project)
    print_report(assessment.report)
    print_stages(assessment.stages)
    if not assessment.report.ok:
        raise typer.Exit(code=1)


def build(
    project: ProjectArg,
    png: Annotated[bool, typer.Option("--png", help="Ещё PNG листов из DXF в out/sheets/")] = False,
) -> None:
    """Проверить проект, записать отчёт и собрать out/project.dxf из этапов, которые можно
    строить: модель и лист на каждый этап, плюс артефакт .epd для просмотра. PNG для проверки —
    render-artifact (из .epd, как в просмотрщике)."""
    with exit_on(AuditError, code=2):
        result = build_project(project, previews=png)
    print_report(result.assessment.report)
    print_stages(result.assessment.stages)
    for path in result.report_files:
        typer.echo(f"  {path}")
    if not result.built:
        fail("Сборка остановлена: план нельзя построить — см. отчёт.")
    assert result.dxf is not None and result.artifact is not None
    for issue in result.price_issues:
        typer.secho(
            f"  {issue.file}: {issue.path}: {issue.message} — смета на листе без цен",
            fg=typer.colors.YELLOW,
        )
    typer.echo(f"  {result.dxf} — аудит без ошибок")
    typer.echo(f"  {result.artifact} — {result.artifact.stat().st_size // 1024} КБ")
    if result.journal is not None:
        typer.echo(f"  {result.journal} — кабельный журнал (проводка через коробки)")
    if result.chases is not None:
        typer.echo(f"  {result.chases} — ведомость штроб")
    if result.loads is not None:
        typer.echo(f"  {result.loads} — роспись потребителей щита")
    if result.stickers is not None:
        typer.echo(f"  {result.stickers} — маркировка щита для печати (рядом цветная, без букв)")
    if result.estimate:
        typer.echo(f"  {result.estimate[-1]} — смета (и .md, .csv рядом)")
    if result.plumbing_estimate:
        typer.echo(f"  {result.plumbing_estimate[-1]} — смета сантехники (и .md, .csv рядом)")
    if result.sewer_routes is not None:
        typer.echo(f"  {result.sewer_routes} — трассы канализации (участки, зоны, высоты, ошибки)")
    for sheet_png in result.sheets:
        typer.echo(f"  {sheet_png}")


def print_album(
    project: ProjectArg,
    paper: Annotated[
        str,
        typer.Option(
            "--paper",
            help="Формат комплекта: auto — как при build, или A4 / A3 / A2 / A1 / A0 "
            "(листы раскладываются заново, масштаб подбирается под формат)",
        ),
    ] = "auto",
) -> None:
    """PDF-альбом листов в натуральную величину: страница — формат листа, печать «в размер»
    даёт масштаб чертежа. Проверяет самый мелкий текст и выход за рамку."""
    formats: tuple[SheetFormat, ...] = ("auto", "A4", "A3", "A2", "A1", "A0")
    fmt = next((f for f in formats if f.lower() == paper.lower()), None)
    if fmt is None:
        fail(f"Формат «{paper}»: нужен один из {', '.join(formats)}", code=2)
    with exit_on(AuditError, code=2):
        result = print_project(project, fmt)
    for issue in result.issues:
        typer.secho(f"  {issue.file}: {issue.message}", fg=typer.colors.YELLOW)
    if result.pdf is None:
        raise typer.Exit(code=1)
    typer.echo(f"Формат {result.paper}, масштаб 1:{result.scale:g}, листов: {len(result.checks)}")
    for sheet_check in result.checks:
        text = f"{sheet_check.min_text:.1f} мм" if sheet_check.min_text is not None else "—"
        typer.echo(f"  {sheet_check.tab}: мелкий текст {text}")
    for warning in result.warnings:
        typer.secho(f"  [внимание] {warning}", fg=typer.colors.YELLOW)
    if result.dxf is not None:
        typer.echo(f"  {result.dxf} — DXF под формат {result.paper}")
    typer.echo(f"  {result.pdf}")


def preview(project: ProjectArg) -> None:
    """PNG листов уже собранного out/project.dxf без перегенерации."""
    out = project / OUT_DIR
    sheets = render_sheets(out)
    for png in sheets:
        typer.echo(f"  {png}")
    if not sheets:
        fail(f"Нет {out / PROJECT_FILE} — сначала build.")


def render_artifact(project: ProjectArg) -> None:
    """PNG страниц из out/project.epd — так, как их построит кабинет (без DXF)."""
    out = project / OUT_DIR
    epd = out / ARTIFACT_FILE
    if not epd.exists():
        fail(f"Нет {epd} — сначала build.")
    target = out / ARTIFACT_PREVIEW_DIR
    for old in target.glob("*.png"):
        old.unlink()
    _, pages = read_artifact(epd)
    for page in pages:
        png = render_page_png(page, target / sheet_png_name(page["name"]))
        typer.echo(f"  {png} — «{page['name']}», примитивов {len(page['items'])}")


def estimate(
    project: ProjectArg,
    prices: Annotated[
        Path | None,
        typer.Option(help="Прайс (по умолчанию — prices.yaml проекта, иначе общий прайс студии)"),
    ] = None,
) -> None:
    """Смета электрики таблицей (без чертежа): out/estimate.md, .csv и .xlsx (Excel с формулами)."""
    result = estimate_project(project, prices)
    if result.prices is not None:
        typer.echo(f"Цены: {result.prices}")
    if result.estimate is not None and result.estimate.from_service:
        typer.echo(f"Сервис цен (имитация): {result.estimate.from_service} поз.")
    for issue in result.issues:
        typer.secho(str(issue), fg=typer.colors.RED)
    if result.estimate is None:
        raise typer.Exit(code=1)
    est = result.estimate
    cur = est.currency
    typer.echo(f"Материалы:        {est.subtotal('material'):,.0f} {cur}".replace(",", " "))
    typer.echo(f"Черновые работы:  {est.subtotal('rough'):,.0f} {cur}".replace(",", " "))
    typer.echo(f"Чистовые работы:  {est.subtotal('finish'):,.0f} {cur}".replace(",", " "))
    typer.echo(f"Всего:            {est.total:,.0f} {cur}".replace(",", " "))
    if est.unpriced:
        typer.secho(f"Без цены: {est.unpriced} поз. — в итог не входят", fg=typer.colors.YELLOW)
    for path in result.files:
        typer.echo(f"  {path}")


def symbols(
    folder: Annotated[Path, typer.Argument(help="Куда выгрузить блоки УГО")] = Path("symbols"),
) -> None:
    """Выгрузить блоки УГО (розетка, выключатель, светильник, щит) в отдельные DXF."""
    for path in export_symbols(folder):
        typer.echo(f"  {path}")
