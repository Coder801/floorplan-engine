"""Работа с боевым сервером из терминала (railway ssh): ядро не трогает, команды — те же
`floorplan-engine project …`, но внутри контейнера: файлы сборок лежат на его volume, а `push`
с ноутбука оставил бы их на ноутбуке.

    uv run python scripts/server.py check                       # что в контейнере, без секретов
    uv run python scripts/server.py rebuild [имена…] [--wait]   # пересобрать текущим кодом
    uv run python scripts/server.py send <проект> room.yaml …   # файлы модели — новой версией
    uv run python scripts/server.py studio-prices [--pull] [--yes] [--rebuild]  # прайс студии
    uv run python scripts/server.py backup [--to папка]         # копия базы и файлов на ноутбук

Модель на сервере — правда (docs/database.md), поэтому send сначала показывает разницу с тем, что
лежит в базе: там могут быть правки, которых нет в папке. Шлётся любой файл модели, кроме
wiring.yaml; answers.yaml и variant.yaml пишет и просмотр — перед их разницей send предупреждает,
что ответы и выбор, записанные на сервере и отсутствующие в папке, пропадут.

studio-prices: projects/prices.yaml — прайс студии владельца ($SHTROBA_OWNER) на сервере, тоже
после разницы с базой; --pull — наоборот, с сервера в папку. Профиль студии (studio.yaml) не
трогается: push идёт из пустой временной папки, где лежит только prices.yaml. Сметы проектов
сами не пересобираются — --rebuild или потом `rebuild`.

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
# Файлы модели, которые шлёт папка: все, что хранит база (repositories.MODEL_COLUMNS), кроме
# wiring.yaml — правки трасс старого образца, их никто больше не пишет (CLAUDE.md, «wiring.yaml»)
MODEL_FILES = (
    "room.yaml",
    "electrical.yaml",
    "plumbing.yaml",
    "furniture.yaml",
    "intake.yaml",
    "answers.yaml",
    "variant.yaml",
)
# Их пишет и просмотр: на сервере могут быть ответы и выбор, которых нет в папке
VIEWER_FILES = ("answers.yaml", "variant.yaml")
# Свой прайс проекта: только исключения поверх прайса студии (решение 2026-11-25). Нет файла в
# папке — send удаляет прайс проекта на сервере, смета берёт прайс студии
PRICES_FILE = "prices.yaml"
SEND_FILES = (*MODEL_FILES, PRICES_FILE)
# Студия и проекты на сервере — владельца из переменной контейнера
OWNER = '--owner "${SHTROBA_OWNER:?не задан владелец}"'
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
    target = shlex.join(names) if names else OWNER
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


def write_files(project: str, files: dict[str, str | None]) -> None:
    """Файлы — в папку проекта с сервера и push оттуда; None удаляет файл (прайс проекта). Push
    собирает только новую версию модели: если менялся один прайс, проект пересобирается сам."""
    folder = f'"$w"/{shlex.quote(project)}'
    body = ""
    for name, text in files.items():
        path = f"{folder}/{shlex.quote(name)}"
        if text is None:
            body += f"rm -f {path}\n"
            continue
        packed = base64.b64encode(text.encode("utf-8")).decode("ascii")
        body += f"echo {packed} | base64 -d > {path}\n"
    body += f"floorplan-engine project push {folder}\n"
    if set(files) == {PRICES_FILE}:
        body += f"floorplan-engine project build {shlex.quote(project)}\n"
    remote(_pulled(project, body))


def send(project: str, names: list[str], yes: bool = False) -> None:
    """Файлы модели из projects/<проект> — на сервер новой версией, разница — до записи;
    prices.yaml — прайс проекта: нет его в папке — на сервере он удаляется."""
    if bad := sorted(set(names) - set(SEND_FILES)):
        raise ServerError(f"{', '.join(bad)}: можно только {', '.join(SEND_FILES)}")
    folder = ROOT / "projects" / project
    changed: dict[str, str | None] = {}
    for name in names:
        path = folder / name
        if not path.is_file() and name != PRICES_FILE:
            raise ServerError(f"нет файла {path}")
        ours = path.read_text(encoding="utf-8") if path.is_file() else None
        theirs = read_file(project, name)
        if (ours or "") == theirs:
            print(f"{name}: совпадает с сервером")
            continue
        changed[name] = ours
        if ours is None:
            print(f"{name}: в папке нет — прайс проекта на сервере удалится, смета — по студии")
        if name in VIEWER_FILES:
            print(
                f"ВНИМАНИЕ: {name} пишет и просмотр (ответы, вариант проводки) — что записано "
                "на сервере и чего нет в папке, пропадёт; смотрите строки «-» ниже"
            )
        print(
            "".join(
                difflib.unified_diff(
                    theirs.splitlines(keepends=True),
                    (ours or "").splitlines(keepends=True),
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


def _diff(old: str, new: str, old_name: str, new_name: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), old_name, new_name
        )
    )


def read_studio_prices() -> str:
    """Прайс студии владельца на сервере; нет прайса — пустая строка."""
    body = (
        "w=$(mktemp -d)\ntrap 'rm -rf \"$w\"' EXIT\n"
        f'floorplan-engine studio pull "$w" {OWNER} >&2\n'
        f'echo {FILE_START}\nif [ -f "$w"/{PRICES_FILE} ]; then base64 < "$w"/{PRICES_FILE}; fi\n'
        f"echo {FILE_END}\n"
    )
    return base64.b64decode(between(remote(body, capture=True))).decode("utf-8")


def write_studio_prices(text: str) -> None:
    """Прайс — в студию владельца на сервере. Папка для studio push — новая и пустая, в ней только
    prices.yaml: без studio.yaml профиль студии не меняется (sync.push_studio)."""
    packed = base64.b64encode(text.encode("utf-8")).decode("ascii")
    remote(
        "w=$(mktemp -d)\ntrap 'rm -rf \"$w\"' EXIT\n"
        f'echo {packed} | base64 -d > "$w"/{PRICES_FILE}\n'
        f'floorplan-engine studio push "$w" {OWNER}\n'
    )


def studio_prices(pull: bool = False, yes: bool = False, rebuild_after: bool = False) -> None:
    """projects/prices.yaml ↔ прайс студии на сервере; разница и вопрос — до записи."""
    path = ROOT / "projects" / PRICES_FILE
    ours = path.read_text(encoding="utf-8") if path.is_file() else ""
    if not pull and not ours:
        raise ServerError(f"нет файла {path}")
    theirs = read_studio_prices()
    if pull and not theirs:
        raise ServerError("у студии на сервере нет прайса: папка не менялась")
    if ours == theirs:
        print(f"{PRICES_FILE}: совпадает с сервером")
        return
    if pull:
        print(_diff(ours, theirs, f"папка/{PRICES_FILE}", f"сервер/{PRICES_FILE}"))
        question = f"Заменить {path} прайсом с сервера? [y/N] "
    else:
        print(_diff(theirs, ours, f"сервер/{PRICES_FILE}", f"папка/{PRICES_FILE}"))
        question = "Заменить прайс студии на сервере? [y/N] "
    if not yes and input(question).lower() != "y":
        raise ServerError("отменено, ничего не менялось")
    if pull:
        path.write_text(theirs, encoding="utf-8")
        print(f"{path}: прайс студии с сервера")
        return
    write_studio_prices(ours)
    if rebuild_after:
        rebuild([])
    else:
        print("Сметы на сервере — по старому прайсу до пересборки: server.py rebuild")


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
    p = sub.add_parser("send", help="файл модели или прайс проекта — на сервер")
    p.add_argument("project")
    p.add_argument("files", nargs="+", help=", ".join(SEND_FILES))
    p.add_argument("--yes", action="store_true", help="не спрашивать")
    p = sub.add_parser("studio-prices", help="прайс студии (projects/prices.yaml) — на сервер")
    p.add_argument("--pull", action="store_true", help="наоборот: с сервера в projects/")
    p.add_argument("--yes", action="store_true", help="не спрашивать")
    p.add_argument("--rebuild", action="store_true", help="после записи пересобрать проекты")
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
        elif args.command == "studio-prices":
            studio_prices(pull=args.pull, yes=args.yes, rebuild_after=args.rebuild)
        else:
            send(args.project, args.files, yes=args.yes)
    except ServerError as e:
        print(f"server: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
