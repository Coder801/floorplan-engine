"""Локальная копия боевых данных (docs/development.md, «Локально как на сервере»).

    uv run python scripts/local.py restore [--from ~/shtroba-backups] [--dump файл] [--yes]

Берёт копию из `scripts/server.py backup`: последний дамп базы — в локальную базу из
`docker compose` (DATABASE_URL из .env, только localhost; база стирается целиком), затем
миграции до текущего кода; зеркало хранилища — в SHTROBA_OBJECTS (по умолчанию data/objects,
папка заменяется). Зеркало копии не трогается: локальные правки пишутся в свою папку.

pg_restore — из образа postgres:18, как и pg_dump в backup: локальный клиент может быть старше
дампа. Пароль — через окружение, не аргументом (виден в ps).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import URL, make_url

from floorplan_engine.cli import load_env
from floorplan_engine.service.db.session import database_url

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = Path.home() / "shtroba-backups"  # как в scripts/server.py
PG_IMAGE = "postgres:18"  # как на Railway
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DOCKER_HOST = "host.docker.internal"  # хост из контейнера; на Linux — через --add-host
RESET = "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"


class LocalError(RuntimeError):
    """Восстановление невозможно; текст — для человека."""


def local_url(raw: str) -> URL:
    """Адрес локальной базы; боевую или чужую стереть нельзя."""
    url = make_url(raw)
    if url.host not in LOCAL_HOSTS:
        raise LocalError(f"DATABASE_URL — {url.host}: стирать можно только локальную базу")
    if not url.database or url.database.endswith("_test"):
        raise LocalError(f"база {url.database!r} — тестовая или без имени")
    return url


def latest_dump(folder: Path) -> Path:
    """Последний дамп копии: в имени дата shtroba-ГГГГ-ММ-ДД-ЧЧММ, сортировка по имени."""
    dumps = sorted((folder / "db").glob("shtroba-*.dump"))
    if not dumps:
        raise LocalError(f"в {folder / 'db'} нет дампов — сначала scripts/server.py backup")
    return dumps[-1]


def pg(url: URL, *command: str) -> list[str]:
    """Команда клиента Postgres в контейнере, нацеленная на локальную базу по url."""
    return [
        "docker", "run", "-i", "--rm", f"--add-host={DOCKER_HOST}:host-gateway",
        "-e", "PGPASSWORD", PG_IMAGE, *command,
        "--host", DOCKER_HOST, "--port", str(url.port or 5432),
        "--username", url.username or "postgres", "--dbname", url.database or "",
    ]  # fmt: skip


def restore_database(url: URL, dump: Path) -> None:
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    steps: list[tuple[str, list[str], Path]] = [
        ("psql", ["--quiet", "--set=ON_ERROR_STOP=1", f"--command={RESET}"], Path(os.devnull)),
        ("pg_restore", ["--no-owner", "--no-acl", "--exit-on-error"], dump),
    ]
    for name, options, stdin in steps:
        with stdin.open("rb") as f:
            r = subprocess.run(pg(url, name, *options), stdin=f, capture_output=True, env=env)
        if r.returncode != 0:
            hint = " (docker compose up -d db?)" if b"connect" in r.stderr else ""
            raise LocalError(f"{name}{hint}: {r.stderr.decode(errors='replace').strip()}")
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT)
    if r.returncode != 0:
        raise LocalError("миграции не прошли (alembic upgrade head)")


def restore_objects(mirror: Path, dest: Path) -> int:
    """Зеркало хранилища — в локальную папку файлов; возвращает число файлов."""
    if not mirror.is_dir():
        raise LocalError(f"нет зеркала файлов {mirror}")
    if dest.resolve() == mirror.resolve():
        raise LocalError("SHTROBA_OBJECTS указывает на саму копию: правки попали бы в зеркало")
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(mirror, dest)
    return sum(1 for p in dest.rglob("*") if p.is_file())


def restore(folder: Path, dump: Path | None, yes: bool) -> None:
    load_env(ROOT / ".env")
    url = local_url(database_url())
    dump = dump or latest_dump(folder)
    dest = Path(os.environ.get("SHTROBA_OBJECTS", "data/objects"))
    dest = dest if dest.is_absolute() else ROOT / dest
    print(f"дамп: {dump}\nбаза: {url.database} на {url.host}:{url.port} — будет стёрта")
    print(f"файлы: {folder / 'objects'} → {dest} — папка будет заменена")
    if not yes and input("Продолжить? [y/N] ").strip().lower() not in {"y", "yes", "д", "да"}:
        raise LocalError("отменено")
    restore_database(url, dump)
    print("база восстановлена, миграции применены")
    print(f"файлы: {restore_objects(folder / 'objects', dest)} шт.")
    if os.environ.get("SHTROBA_STORAGE", "").lower() != "db":
        print("ВНИМАНИЕ: в .env нет SHTROBA_STORAGE=db — просмотр возьмёт проекты из папки")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Локальная копия боевых данных")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("restore", help="копию server.py backup — в локальную базу и файлы")
    p.add_argument("--from", dest="folder", type=Path, default=BACKUP_DIR, help="папка копии")
    p.add_argument("--dump", type=Path, help="дамп базы (по умолчанию — последний в копии)")
    p.add_argument("--yes", action="store_true", help="не спрашивать")
    args = parser.parse_args(argv)
    try:
        restore(args.folder.expanduser(), args.dump, yes=args.yes)
    except LocalError as e:
        print(f"local: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
