"""Версия в web/package-lock.json при релизе (pre_bump_hooks в pyproject.toml,
[tool.commitizen]): commitizen правит только файлы версии, а в lock-файле строка «version»
есть у каждого пакета — менять по образцу нельзя. Здесь меняются только две записи корня
(верхняя и packages[""]), файл пишется, как его пишет npm (отступ 2, перевод строки в конце),
и ставится в индекс: cz bump коммитит индекс вместе с файлами версии.

Новая версия — из переменной CZ_PRE_NEW_VERSION (её даёт commitizen); для проверки руками —
аргументом: `uv run python scripts/release_lock.py 0.2.0 --no-add`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

LOCK = Path(__file__).resolve().parents[1] / "web" / "package-lock.json"


def set_version(lock: Path, version: str) -> None:
    data = json.loads(lock.read_text(encoding="utf-8"))
    data["version"] = version
    data["packages"][""]["version"] = version
    lock.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    version = args[0] if args else os.environ.get("CZ_PRE_NEW_VERSION")
    if not version:
        print("release_lock: нет версии — CZ_PRE_NEW_VERSION или аргумент", file=sys.stderr)
        return 2
    set_version(LOCK, version)
    if "--no-add" not in argv:
        subprocess.run(["git", "add", str(LOCK)], check=True)
    print(f"release_lock: {LOCK.name} → {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
