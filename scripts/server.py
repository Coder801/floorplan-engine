"""Работа с боевым сервером из терминала (railway ssh): ядро не трогает, команды — те же
`floorplan-engine project …`, но внутри контейнера: файлы сборок лежат на его volume, а `push`
с ноутбука оставил бы их на ноутбуке.

    uv run python scripts/server.py check                       # что в контейнере, без секретов
    uv run python scripts/server.py rebuild [имена…] [--wait]   # пересобрать текущим кодом
    uv run python scripts/server.py send <проект> room.yaml …   # файл модели — новой версией
    uv run python scripts/server.py backup [--to папка]         # копия базы и файлов на ноутбук

Модель на сервере — правда (docs/database.md), поэтому send сначала показывает разницу с тем, что
лежит в базе: там могут быть правки, которых нет в папке.

backup: база — pg_dump здесь, в Docker, по публичному адресу сервиса Postgres (в контейнере
сервиса pg_dump нет); файлы хранилища — через ssh пачками tar. Ключ файла после записи не
меняется (источник — по sha256, сборка — по своему id), поэтому файлы докачиваются: в папке
копии лежит зеркало хранилища, а дамп базы и список файлов на тот момент — с датой.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Скрипт — одним аргументом и в base64: CLI склеивает аргументы и отдаёт их sh -c, stdin у него
# рвёт соединение (railway 4.x, WebSocket), кавычки не страдают
SSH = ("railway", "ssh", "--")
DONE = "__shtroba_done__"  # код выхода через CLI не проверен: дошёл ли скрипт до конца — по метке
FILE_START, FILE_END = "__shtroba_file__", "__shtroba_end__"
MODEL_FILES = ("room.yaml", "electrical.yaml", "plumbing.yaml")  # остальные пишет просмотр
DB_SERVICE = "Postgres"  # сервис базы в проекте Railway
PG_IMAGE = "postgres:18"  # pg_dump не старше сервера быть не может, 18 снимает и 17
BACKUP_DIR = Path.home() / "shtroba-backups"  # данные клиентов: вне репозитория
BATCH_BYTES = 8 * 1024 * 1024  # файлов за один ssh: ответ идёт base64 в памяти
LIST_OBJECTS = (
    'cd "$SHTROBA_OBJECTS"\n'
    f"echo {FILE_START}\nfind . -type f -printf '%s %P\\n'\necho {FILE_END}\n"
)
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
echo "хранилище: $SHTROBA_OBJECTS, файлов: $(find "$SHTROBA_OBJECTS" -type f 2>/dev/null | wc -l)"
echo "диск (должен быть отдельный том, а не overlay): $(df -P "$SHTROBA_OBJECTS" | tail -1)"
for v in DATABASE_URL SHTROBA_OWNER SHTROBA_AUTH; do
  eval "set_=\\${$v+задана}"
  echo "$v: ${set_:-НЕ ЗАДАНА}"
done
echo "команда: $(command -v floorplan-engine || echo НЕТ)"
"""


class ServerError(Exception):
    """Ошибка для человека, без трассировки."""


def remote(script: str, capture: bool = False) -> str:
    """Скрипт в контейнере; capture — вернуть вывод, иначе показать его."""
    packed = base64.b64encode(f"{PRELUDE}{script}echo {DONE}\n".encode()).decode("ascii")
    command = [*SSH, f"echo {packed}|base64 -d|sh"]
    r = subprocess.run(command, stdin=subprocess.DEVNULL, text=True, capture_output=True)
    out = r.stdout.replace("\r\n", "\n")
    if r.returncode != 0 or DONE not in out:
        raise ServerError(f"railway ssh: код {r.returncode}\n{out}{r.stderr}".strip())
    out = out.replace(f"{DONE}\n", "")
    if not capture:
        print(out, end="")
    return out


def local_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as f:
        version: str = tomllib.load(f)["project"]["version"]
    return version


def server_version() -> str:
    return remote(f"python -c {shlex.quote(VERSION_CODE)}\n", capture=True).split()[-1]


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
    body = f"echo {FILE_START}\nif [ -f {path} ]; then base64 < {path}; fi\necho {FILE_END}\n"
    return base64.b64decode(between(remote(_pulled(project, body), capture=True))).decode("utf-8")


def between(out: str) -> str:
    """Вывод скрипта между метками: до них — то, что печатают сами команды."""
    if FILE_START not in out or FILE_END not in out:
        raise ServerError(f"в ответе нет данных:\n{out[-2000:]}")
    return out.split(FILE_START, 1)[1].split(FILE_END, 1)[0]


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


def database_url(service: str = DB_SERVICE) -> str:
    """Публичный адрес базы из переменных сервиса; на экран не выводится."""
    r = subprocess.run(
        ["railway", "variables", "--service", service, "--kv"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise ServerError(f"railway variables --service {service}: {r.stderr.strip()}")
    for line in r.stdout.splitlines():
        name, _, value = line.partition("=")
        if name == "DATABASE_PUBLIC_URL" and value:
            return value
    raise ServerError(
        f"у сервиса {service} нет DATABASE_PUBLIC_URL: включите публичный доступ (TCP Proxy)"
    )


def dump_database(url: str, dest: Path) -> int:
    """pg_dump в формате custom; адрес — через окружение, не аргументом (виден в ps).
    Возвращает число таблиц с данными в дампе: pg_restore --list читает его целиком."""
    env = {**os.environ, "DATABASE_URL": url}
    dump = ("sh", "-c", 'exec pg_dump --format=custom --dbname="$DATABASE_URL"')
    part = dest.with_name(dest.name + ".part")
    if shutil.which("docker") is None:
        raise ServerError(f"нужен Docker: pg_dump запускается из образа {PG_IMAGE}")
    with part.open("wb") as f:
        r = subprocess.run(
            ["docker", "run", "--rm", "-e", "DATABASE_URL", PG_IMAGE, *dump],
            stdin=subprocess.DEVNULL,
            stdout=f,
            stderr=subprocess.PIPE,
            text=False,
            env=env,
        )
    if r.returncode != 0:
        part.unlink(missing_ok=True)
        hint = " (Docker запущен?)" if b"docker" in r.stderr.lower() else ""
        raise ServerError(f"pg_dump{hint}: {r.stderr.decode(errors='replace').strip()}")
    with part.open("rb") as f:
        check = subprocess.run(
            ["docker", "run", "-i", "--rm", PG_IMAGE, "pg_restore", "--list"],
            stdin=f,
            capture_output=True,
            text=True,
        )
    if check.returncode != 0:
        raise ServerError(f"дамп не читается ({part}): {check.stderr.strip()}")
    part.rename(dest)
    return sum(" TABLE DATA " in line for line in check.stdout.splitlines())


def server_objects() -> dict[str, int]:
    """Файлы хранилища на volume: ключ → размер."""
    found: dict[str, int] = {}
    for line in between(remote(LIST_OBJECTS, capture=True)).splitlines():
        size, _, key = line.strip().partition(" ")
        if key:
            found[key] = int(size)
    return found


def missing(objects: dict[str, int], mirror: Path) -> list[str]:
    """Ключи, которых в зеркале нет или размер другой (оборванная прошлая копия)."""
    return [
        key
        for key, size in sorted(objects.items())
        if not (path := mirror / key).is_file() or path.stat().st_size != size
    ]


def batches(keys: list[str], sizes: dict[str, int], limit: int = BATCH_BYTES) -> list[list[str]]:
    """Ключи пачками не больше limit байт; файл крупнее — пачкой из одного."""
    out: list[list[str]] = []
    total = 0
    for key in keys:
        if out and total + sizes[key] <= limit:
            out[-1].append(key)
            total += sizes[key]
        else:
            out.append([key])
            total = sizes[key]
    return out


def fetch(keys: list[str], mirror: Path) -> None:
    """Пачка файлов хранилища — tar через ssh — в зеркало. Имена ключей без переводов строки
    (objects.check_key), поэтому список — построчно."""
    listing = base64.b64encode("".join(f"{k}\n" for k in keys).encode()).decode("ascii")
    script = (
        "l=$(mktemp)\ntrap 'rm -f \"$l\"' EXIT\n"
        f'echo {listing} | base64 -d > "$l"\n'
        f'echo {FILE_START}\ntar -C "$SHTROBA_OBJECTS" -cf - -T "$l" | base64\necho {FILE_END}\n'
    )
    data = base64.b64decode(between(remote(script, capture=True)))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        tar.extractall(mirror, filter="data")


def backup(to: Path, service: str = DB_SERVICE) -> None:
    """Дамп базы и список файлов с датой, затем докачка зеркала хранилища."""
    stamp = time.strftime("%Y-%m-%d-%H%M")
    db_dir, mirror = to / "db", to / "objects"
    db_dir.mkdir(parents=True, exist_ok=True)
    mirror.mkdir(parents=True, exist_ok=True)
    dump = db_dir / f"shtroba-{stamp}.dump"
    tables = dump_database(database_url(service), dump)
    print(f"база: {dump} ({dump.stat().st_size // 1024} КБ, таблиц с данными: {tables})")
    objects = server_objects()
    listing = "".join(f"{size} {key}\n" for key, size in sorted(objects.items()))
    (db_dir / f"shtroba-{stamp}-objects.txt").write_text(listing, encoding="utf-8")
    todo = missing(objects, mirror)
    for i, keys in enumerate(batches(todo, objects), 1):
        print(f"файлы: пачка {i}, {len(keys)} шт.", flush=True)
        fetch(keys, mirror)
    if still := missing(objects, mirror):
        raise ServerError(f"не скачались {len(still)} файлов, первый: {still[0]}")
    size = sum(objects.values()) // (1024 * 1024)
    print(f"файлы: {mirror} — {len(objects)} шт., {size} МБ, новых {len(todo)}")


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
    p = sub.add_parser("backup", help="копия базы и файлов хранилища на этот компьютер")
    p.add_argument("--to", type=Path, default=BACKUP_DIR, help=f"папка (по умолчанию {BACKUP_DIR})")
    p.add_argument("--db-service", default=DB_SERVICE, help="сервис базы в Railway")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(f"версия: сервер {server_version()}, здесь {local_version()}")
            remote(CHECK)
        elif args.command == "rebuild":
            rebuild(args.names, wait=args.wait)
        elif args.command == "backup":
            backup(args.to.expanduser(), service=args.db_service)
        else:
            send(args.project, args.files, yes=args.yes)
    except ServerError as e:
        print(f"server: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
