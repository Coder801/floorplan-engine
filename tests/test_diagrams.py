"""The Mermaid diagrams in docs/diagrams.md match the code: the layer order matches the
import-linter contract, the project states match ProjectState, the frontend groups and their
allowed imports match web/src/structure.test.ts and the model classes exist in model/."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from floorplan_engine.model import intake, plumbing, schema
from floorplan_engine.service.models import ProjectState

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "diagrams.md"
PACKAGE = "floorplan_engine."


def mermaid(section: str) -> str:
    """The Mermaid block under the `## section` heading."""
    text = DOC.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(section)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"нет раздела «{section}» в {DOC.name}"
    block = re.search(r"```mermaid\n(.*?)```", match.group(1), re.S)
    assert block, f"нет схемы Mermaid в разделе «{section}»"
    return block.group(1)


def test_layers_match_import_linter() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = pyproject["tool"]["importlinter"]["contracts"]
    contract = next(c for c in contracts if c["type"] == "layers")
    expected = [layer.removeprefix(PACKAGE) for layer in contract["layers"]]
    chain = max(mermaid("Слои ядра").splitlines(), key=lambda line: line.count("-->"))
    assert [node.strip() for node in chain.split("-->")] == expected
    declared = re.findall(r"^\s+(\w+)\[\"", mermaid("Слои ядра"), re.M)
    assert sorted(declared) == sorted(expected)


def test_states_match_project_state() -> None:
    transitions = re.findall(r"^\s+(\S+) --> (\S+)", mermaid("Состояния проекта в сервисе"), re.M)
    states = {s for pair in transitions for s in pair} - {"[*]"}
    assert states == {state.value for state in ProjectState}


def test_frontend_groups_match_structure_test() -> None:
    source = (ROOT / "web" / "src" / "structure.test.ts").read_text(encoding="utf-8")
    allowed_block = re.search(r"const ALLOWED[^{]*\{(.*?)\n\};", source, re.S)
    assert allowed_block
    allowed = {
        group: set(re.findall(r'"(\w+)"', targets)) - {group}
        for group, targets in re.findall(r"(\w+): \[([^\]]*)\]", allowed_block.group(1))
    }
    block = mermaid("Фронт web/")
    declared = set(re.findall(r"^\s+(\w+)\[\"", block, re.M))
    assert declared == set(allowed)
    drawn: dict[str, set[str]] = {group: set() for group in allowed}
    for source_group, targets in re.findall(r"^\s+(\w+) --> (.+)$", block, re.M):
        drawn[source_group] |= {t.strip() for t in targets.split("&")}
    assert drawn == allowed


@pytest.mark.parametrize(
    ("name", "module"),
    [
        ("Plan", schema),
        ("Electrical", schema),
        ("Studio", schema),
        ("Plumbing", plumbing),
        ("Intake", intake),
        ("Answers", intake),
    ],
)
def test_model_classes_exist(name: str, module: object) -> None:
    assert hasattr(module, name), f"{name} нет в {module}"


def test_model_diagram_lists_every_schema_file() -> None:
    classes = set(re.findall(r"^\s+class (\w+) \{", mermaid("Модель проекта"), re.M))
    assert classes == {"Plan", "Electrical", "Plumbing", "Intake", "Answers", "Studio"}
