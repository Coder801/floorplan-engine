"""Local copy of production data (scripts/local.py): only a local database is wiped, the backup
mirror is never written to."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local", ROOT / "scripts" / "local.py")
assert spec is not None and spec.loader is not None
local = importlib.util.module_from_spec(spec)
sys.modules["local"] = local
spec.loader.exec_module(local)


def test_only_a_local_database_is_wiped() -> None:
    url = local.local_url("postgresql+psycopg://u:p@localhost:5433/floorplan_engine")
    assert (url.host, url.port, url.database) == ("localhost", 5433, "floorplan_engine")
    with pytest.raises(local.LocalError, match="только локальную"):
        local.local_url("postgresql://u:p@db.proxy.rlwy.net:41234/railway")
    with pytest.raises(local.LocalError, match="тестовая"):
        local.local_url("postgresql+psycopg://u:p@127.0.0.1:5433/floorplan_engine_test")


def test_latest_dump_by_date_in_the_name(tmp_path: Path) -> None:
    with pytest.raises(local.LocalError, match=r"server\.py backup"):
        local.latest_dump(tmp_path)
    (tmp_path / "db").mkdir()
    for stamp in ("2026-11-12-0930", "2026-11-12-1015", "2026-11-04-2359"):
        (tmp_path / "db" / f"shtroba-{stamp}.dump").touch()
    (tmp_path / "db" / "shtroba-2026-11-12-1015-objects.txt").touch()
    assert local.latest_dump(tmp_path).name == "shtroba-2026-11-12-1015.dump"


def test_postgres_client_runs_in_the_image_without_password_in_args() -> None:
    url = local.local_url("postgresql+psycopg://u:secret@localhost:5433/fe")
    command = local.pg(url, "pg_restore", "--no-owner")
    assert command[:2] == ["docker", "run"] and local.PG_IMAGE in command
    assert "secret" not in " ".join(command)
    assert command[command.index("--port") + 1] == "5433"
    assert command[command.index("--dbname") + 1] == "fe"


def test_restore_database_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe the schema, restore the dump, then migrate to the current code."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def run(command: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((command, kw))
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(local.subprocess, "run", run)
    dump = tmp_path / "x.dump"
    dump.write_bytes(b"PGDMP")
    local.restore_database(local.local_url("postgresql://u:pw@localhost/fe"), dump)
    names = [next(a for a in c if a in {"psql", "pg_restore", "alembic"}) for c, _ in calls]
    assert names == ["psql", "pg_restore", "alembic"]
    assert calls[0][1]["env"]["PGPASSWORD"] == "pw"


def test_restore_database_reports_the_failing_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(command: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 1, b"", b"could not connect to server")

    monkeypatch.setattr(local.subprocess, "run", run)
    with pytest.raises(local.LocalError, match=r"psql \(docker compose up -d db\?\)"):
        local.restore_database(local.local_url("postgresql://u@localhost/fe"), tmp_path / "x")


def test_objects_replace_the_local_folder_not_the_mirror(tmp_path: Path) -> None:
    mirror = tmp_path / "backup" / "objects"
    (mirror / "src").mkdir(parents=True)
    (mirror / "src" / "ab").write_bytes(b"1")
    dest = tmp_path / "data" / "objects"
    dest.mkdir(parents=True)
    (dest / "stale").write_bytes(b"0")
    assert local.restore_objects(mirror, dest) == 1
    assert not (dest / "stale").exists() and (dest / "src" / "ab").read_bytes() == b"1"
    with pytest.raises(local.LocalError, match="саму копию"):
        local.restore_objects(mirror, mirror)
    with pytest.raises(local.LocalError, match="нет зеркала"):
        local.restore_objects(tmp_path / "нет", dest)
