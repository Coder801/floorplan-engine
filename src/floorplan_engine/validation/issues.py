"""Замечания проверки и загрузка YAML: файлы модели, Issue с путём к полю и важностью,
перевод ошибок pydantic на русский (`format_loc`, `parse_model`), чтение YAML без падений."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

ROOM_FILE = "room.yaml"
ELECTRICAL_FILE = "electrical.yaml"
WIRING_FILE = "wiring.yaml"  # ручные правки проводки из просмотра (линии, коробки)
STUDIO_FILE = "studio.yaml"  # профиль студии — в папке над проектами
M = TypeVar("M", bound=BaseModel)


class Severity(StrEnum):
    ERROR = "ошибка"
    WARNING = "предупреждение"


@dataclass(frozen=True)
class Issue:
    file: str
    path: str
    message: str
    severity: Severity = Severity.ERROR

    def __str__(self) -> str:
        where = f"{self.file}: {self.path}" if self.path else self.file
        return f"[{self.severity.value}] {where}: {self.message}"


QuestionState = Literal["open", "answered", "accepted", "text"]


def format_loc(loc: Iterable[int | str]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out


def format_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return ""
    return f" (указано: {value!r})"


def _translate(err: Any) -> str:
    kind: str = err["type"]
    ctx: dict[str, Any] = err.get("ctx") or {}
    given = format_value(err.get("input"))
    match kind:
        case "missing":
            return "обязательное поле не заполнено"
        case "extra_forbidden":
            return "неизвестное поле — опечатка или лишний ключ"
        case "greater_than":
            return f"должно быть больше {ctx['gt']}{given}"
        case "greater_than_equal":
            return f"должно быть не меньше {ctx['ge']}{given}"
        case "less_than":
            return f"должно быть меньше {ctx['lt']}{given}"
        case "less_than_equal":
            return f"должно быть не больше {ctx['le']}{given}"
        case "float_parsing" | "float_type" | "int_parsing" | "int_type":
            return f"ожидается число{given}"
        case "int_from_float":
            return f"ожидается целое число{given}"
        case "string_type":
            return f"ожидается строка{given}"
        case "bool_parsing" | "bool_type":
            return f"ожидается true или false{given}"
        case "literal_error" | "enum":
            return f"допустимые значения: {ctx.get('expected', '?')}{given}"
        case "string_pattern_mismatch":
            return f"допустимы только латиница, цифры, _ и -{given}"
        case "string_too_short":
            return "не может быть пустым"
        case "too_short":
            return f"нужно минимум {ctx.get('min_length')} элемента(ов)"
        case "too_long":
            return f"нужно не больше {ctx.get('max_length')} элемента(ов)"
        case "list_type":
            return "ожидается список (- ... или [ ... ])"
        case "tuple_type":
            return "ожидается пара координат [x, y]"
        case "model_type" | "dict_type" | "model_attributes_type":
            return "ожидается объект { ключ: значение }"
        case "value_error":
            return str(err["msg"]).removeprefix("Value error, ")
        case _:
            return str(err["msg"])


def parse_model(model: type[M], data: Any, file: str) -> tuple[M | None, list[Issue]]:
    try:
        return model.model_validate(data), []
    except ValidationError as exc:
        issues = [Issue(file, format_loc(e["loc"]), _translate(e)) for e in exc.errors()]
        return None, issues


def load_yaml(path: Path) -> tuple[Any, list[Issue]]:
    file = path.name
    if not path.exists():
        return None, [Issue(file, "", f"файл не найден: {path}")]
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        where = f"строка {mark.line + 1}, столбец {mark.column + 1}" if mark else ""
        return None, [Issue(file, where, f"синтаксическая ошибка YAML: {exc.problem}")]
    except yaml.YAMLError as exc:
        return None, [Issue(file, "", f"синтаксическая ошибка YAML: {exc}")]
    if data is None:
        return None, [Issue(file, "", "файл пустой")]
    return data, []
