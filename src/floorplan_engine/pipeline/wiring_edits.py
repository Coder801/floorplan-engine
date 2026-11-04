"""Wiring edits from the viewer: wiring.yaml, its text and the rebuild."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from floorplan_engine.model.schema import WiringEdits, WiringFile
from floorplan_engine.validation.issues import (
    WIRING_FILE,
    Issue,
    load_yaml,
    parse_model,
)
from floorplan_engine.validation.validate import validate_project


def save_wiring_edits(project: Path, changes: dict[str, Any]) -> list[Issue]:
    """Save wiring edits from the viewer to the project's wiring.yaml, under the chosen variant
    (variants.<key>): changes = {"wires": {id: edit or None}, "boxes": {...}}; None removes
    the edit (the line becomes an auto route again). Pre-variant edits (top-level wires and
    boxes) move into the "as in project" section when that variant is edited. No edits means
    no file. Errors come with a field path, and the file is left unchanged."""
    path = project / WIRING_FILE
    bad = [
        Issue(WIRING_FILE, kind, "ожидается словарь «id: правка»")
        for kind in ("wires", "boxes")
        if not isinstance(changes.get(kind) or {}, dict)
    ]
    if bad:
        return bad
    report = validate_project(project)
    # Electrical cannot be read, so there is no variant: edits go the old way, outside variant
    # sections
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
        keep_legacy = key != default_key  # pre-variant edits belong to the "as in project" variant
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
    """wiring.yaml with variants: pre-variant edits (if any are left), then variants."""
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
    """Edits of one variant (pre-variant wiring.yaml): one line per box and per line."""
    head = [
        "# Ручные правки проводки из просмотра (floorplan-engine view), мм модели.",
        "# Остальное строится автоматически; удалить запись — вернуть автотрассу.",
    ]
    return "\n".join(head + _edit_lines(edits, "")) + "\n"


def _edit_lines(edits: WiringEdits, indent: str) -> list[str]:
    """Indented edit lines: one line per box and per line, route points on one line."""

    def xy(p: tuple[float, float]) -> str:
        return f"[{p[0]:g}, {p[1]:g}]"

    def q(text: str) -> str:  # a JSON string is also a YAML string, with any characters
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
    """wire_2 before wire_10."""
    head, _, tail = key.rpartition("_")
    return (head, int(tail)) if tail.isdigit() else (key, 0)
