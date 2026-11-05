"""Commands over project sources: LLM analysis and digests without LLM (service/analysis, facts)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from floorplan_engine.cli.common import (
    AnalyzerOpt,
    EffortOpt,
    ElectricalModelOpt,
    ModelOpt,
    ProjectArg,
    exit_on,
    print_report,
    print_stages,
)
from floorplan_engine.pipeline import assess_project


def analyze(
    project: ProjectArg,
    analyzer: AnalyzerOpt = "claude-code",
    model: ModelOpt = "claude-opus-5-5",
    effort: EffortOpt = "medium",
    electrical_model: ElectricalModelOpt = None,
    round_no: Annotated[int, typer.Option("--round", help="Номер раунда")] = 1,
) -> None:
    """LLM-анализ папки проекта: source/ → intake.yaml и YAML этапов (затем — build)."""
    from floorplan_engine.service.analysis.llm_analyzer import AnalyzerError, make_analyzer

    with exit_on(AnalyzerError):
        result = make_analyzer(analyzer, model, effort, electrical_model).analyze(project, round_no)
    typer.echo(result.message)
    typer.echo(f"  вызовов LLM: {result.calls}, стоимость ≈ ${result.cost_usd:.2f}")
    assessment = assess_project(project)
    print_report(assessment.report)
    print_stages(assessment.stages)


def pdf_facts(
    pdf: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Векторный PDF источника")
    ],
    as_json: Annotated[bool, typer.Option("--json", help="JSON вместо Markdown")] = False,
) -> None:
    """Выжимка из PDF без LLM: масштаб листа, размеры, цепочки, надписи с координатами."""
    from floorplan_engine.service.analysis.pdf_facts import describe, describe_json

    typer.echo(describe_json(pdf) if as_json else describe(pdf))


def facts(
    source: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="PDF или картинка источника")
    ],
    as_json: Annotated[bool, typer.Option("--json", help="JSON вместо Markdown")] = False,
) -> None:
    """Выжимка из любого источника без LLM: вектор или растр — по каждой странице сам."""
    import json

    from floorplan_engine.service.facts.analysis import page_facts, render, to_dict
    from floorplan_engine.service.facts.source import read_source

    pages = [page_facts(s) for s in read_source(source)]
    if as_json:
        typer.echo(json.dumps([to_dict(f) for f in pages], ensure_ascii=False, indent=1))
    else:
        typer.echo(render(pages))


def facts_bench(
    pdfs: Annotated[list[Path], typer.Argument(exists=True, dir_okay=False, help="Векторные PDF")],
) -> None:
    """Точность растра: PDF → картинка → растровый разбор, сверка размеров с вектором."""
    from floorplan_engine.service.facts.bench import report, run

    for pdf in pdfs:
        typer.echo(report(pdf.name, run(pdf)))
        typer.echo("")
