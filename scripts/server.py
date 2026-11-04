"""Работа с боевым сервером из терминала (railway ssh): ядро не трогает, команды — те же
`floorplan-engine project …`, но внутри контейнера: файлы сборок лежат на его volume, а `push`
с ноутбука оставил бы их на ноутбуке.

    uv run python scripts/server.py check                       # что в контейнере, без секретов
    uv run python scripts/server.py rebuild [имена…] [--wait]   # пересобрать текущим кодом
    uv run python scripts/server.py send <проект> room.yaml …   # файл модели — новой версией

Модель на сервере — правда (docs/database.md), поэтому send сначала показывает разницу с тем, что
лежит в базе: там могут быть правки, которых нет в папке.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import shlex
import subprocess
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SSH = ("railway", "ssh", "--", "sh", "-s")  # скрипт — через stdin: кавычки не страдают
MODEL_FILES = ("room.yaml", "electrical.yaml", "plumbing.yaml")  # остальные пишет просмотр
WAIT_S = 900.0  # выкладка не дольше этого
POLL_S = 20.0
# Как в deploy/start.sh и Dockerfile: сессия ssh не обязана их наследовать, а без хранилища на
# volume файлы сборок уйдут мимо него
PRELUDE = (
    "set -eu\n"
    'export SHTROBA_OBJECTS="${SHTROBA_OBJECTS:-/data/objects}"\n'
    'export PATH="/app/.venv/bin:$PATH"\n'
    "cd /app\n"
)
VERSION_CODE = "from importlib.metadata import version; print(version('floorplan-engine'))"
CHECK = """
echo "volume: $(test -d "$SHTROBA_OBJECTS" && echo есть || echo НЕТ) ($SHTROBA_OBJECTS)"
for v in DATABASE_URL SHTROBA_OWNER SHTROBA_AUTH; do
  eval "set_=\\${$v+задана}"
  echo "$v: ${set_:-НЕ ЗАДАНА}"
done
echo "команда: $(command -v floorplan-engine || echo НЕТ)"
"""


class ServerError(Exception):
    """Ошибка для человека, без трассировки."""


def remote(script: str, capture: bool = False) -> str:
    """Скрипт в контейнере; capture — вернуть вывод, иначе он идёт в терминал."""
    r = subprocess.run(SSH, input=PRELUDE + script, text=True, capture_output=capture)
    if r.returncode != 0:
        raise ServerError(f"railway ssh: код {r.returncode}{': ' + r.stderr if capture else ''}")
    return r.stdout if capture else ""


def local_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        version: str = tomllib.load(f)["project"]["version"]
    return version


def server_version() -> str:
    return remote(f"python -c {shlex.quote(VERSION_CODE)}\n", capture=True).strip()


def wait_for_version(version: str, timeout: float = WAIT_S, poll: float = POLL_S) -> None:
    """Пока идёт выкладка, контейнер старый или недоступен: ждём версию, которую выпустили."""
    deadline = time.monotonic() + timeout
    last = "нет ответа"
    while True:
        try:
            last = server_version()
            if last == version:
                return
        except ServerError as e:
            last = str(e)
        if time.monotonic() >= deadline:
            raise ServerError(
                f"на сервере не появилась версия {version} (последнее: {last}): "
                "проверьте, какую ветку слушает Railway и прошла ли сборка"
            )
        print(f"ждём {version}, на сервере: {last}", flush=True)
        time.sleep(poll)


def rebuild(names: list[str], wait: bool = False) -> None:
    """Новая сборка текущим кодом; модель не меняется. Без имён — все проекты владельца."""
    version = local_version()
    if wait:
        wait_for_version(version)
    elif (found := server_version()) != version:
        raise ServerError(f"на сервере {found}, здесь {version}: дождитесь выкладки (--wait)")
    target = shlex.join(names) if names else '--owner "${SHTROBA_OWNER:?не задан владелец}"'
    remote(f"floorplan-engine project build {target}\n")


def _pulled(project: str, body: str) -> str:
    """Скрипт: проект из базы во временную папку $w, затем body; папка удаляется в любом случае."""
    name = shlex.quote(project)
    return (
        "w=$(mktemp -d)\ntrap 'rm -rf \"$w\"' EXIT\n"
        f'floorplan-engine project pull {name} --to "$w" >&2\n{body}'
    )


def read_file(project: str, name: str) -> str:
    """Файл модели на сервере; нет такого файла — пустая строка."""
    path = f'"$w"/{shlex.quote(project)}/{shlex.quote(name)}'
    body = f"if [ -f {path} ]; then base64 < {path}; fi\n"
    return base64.b64decode(remote(_pulled(project, body), capture=True)).decode("utf-8")


def write_files(project: str, files: dict[str, str]) -> None:
    folder = f'"$w"/{shlex.quote(project)}'
    body = ""
    for name, text in files.items():
        packed = base64.b64encode(text.encode("utf-8")).decode("ascii")
        body += f"echo {packed} | base64 -d > {folder}/{shlex.quote(name)}\n"
    remote(_pulled(project, f"{body}floorplan-engine project push {folder}\n"))


def send(project: str, names: list[str], yes: bool = False) -> None:
    """Файлы модели из projects/<проект> — на сервер новой версией, разница — до записи."""
    if bad := sorted(set(names) - set(MODEL_FILES)):
        raise ServerError(f"{', '.join(bad)}: можно только {', '.join(MODEL_FILES)}")
    folder = ROOT / "projects" / project
    changed: dict[str, str] = {}
    for name in names:
        path = folder / name
        if not path.is_file():
            raise ServerError(f"нет файла {path}")
        ours = path.read_text(encoding="utf-8")
        theirs = read_file(project, name)
        if ours == theirs:
            print(f"{name}: совпадает с сервером")
            continue
        changed[name] = ours
        print(
            "".join(
                difflib.unified_diff(
                    theirs.splitlines(keepends=True),
                    ours.splitlines(keepends=True),
                    f"сервер/{name}",
                    f"папка/{name}",
                )
            )
        )
    if not changed:
        return
    if not yes and input(f"Заменить на сервере {', '.join(changed)}? [y/N] ").lower() != "y":
        raise ServerError("отменено, сервер не менялся")
    write_files(project, changed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Боевой сервер через railway ssh")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="что в контейнере: версия, volume, переменные (без значений)")
    p = sub.add_parser("rebuild", help="пересобрать проекты текущим кодом")
    p.add_argument("names", nargs="*", help="имена; без них — все проекты владельца")
    p.add_argument("--wait", action="store_true", help="дождаться выкладки этой версии")
    p = sub.add_parser("send", help="файл модели — на сервер новой версией")
    p.add_argument("project")
    p.add_argument("files", nargs="+", help=", ".join(MODEL_FILES))
    p.add_argument("--yes", action="store_true", help="не спрашивать")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(f"версия: сервер {server_version()}, здесь {local_version()}")
            remote(CHECK)
        elif args.command == "rebuild":
            rebuild(args.names, wait=args.wait)
        else:
            send(args.project, args.files, yes=args.yes)
    except ServerError as e:
        print(f"server: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
