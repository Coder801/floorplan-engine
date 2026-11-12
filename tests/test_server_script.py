"""Server commands (scripts/server.py): what goes into the container, with railway replaced."""

from __future__ import annotations

import base64
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("server", ROOT / "scripts" / "server.py")
assert spec is not None and spec.loader is not None
server = importlib.util.module_from_spec(spec)
sys.modules["server"] = server
spec.loader.exec_module(server)


def test_image_points_every_command_to_the_volume() -> None:
    """Commands in railway ssh do not go through start.sh."""
    assert "SHTROBA_OBJECTS=/data/objects" in (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_prelude_points_to_the_volume_like_start_sh() -> None:
    assert 'SHTROBA_OBJECTS="${SHTROBA_OBJECTS:-/data/objects}"' in server.PRELUDE
    start = (ROOT / "deploy" / "start.sh").read_text(encoding="utf-8")
    assert 'SHTROBA_OBJECTS="${SHTROBA_OBJECTS:-/data/objects}"' in start


def _recorded(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def remote(script: str, capture: bool = False) -> str:
        calls.append(script)
        return ""

    monkeypatch.setattr(server, "remote", remote)
    return calls


def test_remote_sends_one_argument_without_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """railway 4.x: stdin breaks the connection, arguments reach sh -c joined."""
    seen: dict[str, Any] = {}

    def run(command: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        seen.update(command=command, **kw)
        return subprocess.CompletedProcess(command, 0, f"ответ\r\n{server.DONE}\r\n", "")

    monkeypatch.setattr(server.subprocess, "run", run)
    assert server.remote("echo 'ответ'\n", capture=True) == "ответ\n"
    command = seen["command"]
    assert command[:3] == ["railway", "ssh", "--"] and len(command) == 4
    assert seen["stdin"] == subprocess.DEVNULL
    script = base64.b64decode(command[3].split()[1].split("|")[0]).decode()
    assert script.startswith(server.PRELUDE) and script.endswith(f"echo {server.DONE}\n")


def test_remote_fails_without_the_end_mark(monkeypatch: pytest.MonkeyPatch) -> None:
    """The script stopped halfway though the CLI returned 0."""
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda c, **_: subprocess.CompletedProcess(c, 0, "половина\n", ""),
    )
    with pytest.raises(server.ServerError, match="половина"):
        server.remote("true\n")


def test_rebuild_refuses_an_old_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _recorded(monkeypatch)
    monkeypatch.setattr(server, "local_version", lambda: "1.2.3")
    monkeypatch.setattr(server, "server_version", lambda: "1.2.2")
    with pytest.raises(server.ServerError, match="--wait"):
        server.rebuild([])
    assert calls == []


def test_rebuild_all_or_named(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _recorded(monkeypatch)
    monkeypatch.setattr(server, "local_version", lambda: "1.2.3")
    monkeypatch.setattr(server, "server_version", lambda: "1.2.3")
    server.rebuild([])
    server.rebuild(["kv42"])
    assert 'project build --owner "${SHTROBA_OWNER' in calls[0]
    assert "project build kv42\n" in calls[1]


def test_wait_for_version_survives_a_redeploy(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter([server.ServerError("нет связи"), "1.2.2", "1.2.3"])

    def version() -> str:
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return str(answer)

    monkeypatch.setattr(server, "server_version", version)
    server.wait_for_version("1.2.3", timeout=10, poll=0)


def test_wait_for_version_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "server_version", lambda: "1.2.2")
    with pytest.raises(server.ServerError, match="ветку"):
        server.wait_for_version("1.2.3", timeout=0, poll=0)


def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr(server, "ROOT", tmp_path)
    folder = tmp_path / "projects" / "kv42"
    folder.mkdir(parents=True)
    (folder / "room.yaml").write_text(text, encoding="utf-8")


def _server_file(monkeypatch: pytest.MonkeyPatch, text: str) -> list[str]:
    calls: list[str] = []

    def remote(script: str, capture: bool = False) -> str:
        calls.append(script)
        packed = base64.b64encode(text.encode("utf-8")).decode("ascii")
        return f"версия 3\n{server.FILE_START}\n{packed}\n{server.FILE_END}\n" if capture else ""

    monkeypatch.setattr(server, "remote", remote)
    return calls


def test_send_writes_only_after_yes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _project(tmp_path, monkeypatch, "окно: 2000\n")
    calls = _server_file(monkeypatch, "окно: 1400\n")
    monkeypatch.setattr("builtins.input", lambda _: "n")
    with pytest.raises(server.ServerError, match="отменено"):
        server.send("kv42", ["room.yaml"])
    assert not any("project push" in c for c in calls)
    server.send("kv42", ["room.yaml"], yes=True)
    packed = base64.b64encode("окно: 2000\n".encode()).decode("ascii")
    assert packed in calls[-1] and 'project push "$w"/kv42' in calls[-1]


def test_send_skips_a_file_equal_to_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path, monkeypatch, "окно: 2000\n")
    calls = _server_file(monkeypatch, "окно: 2000\n")
    server.send("kv42", ["room.yaml"], yes=True)
    assert not any("project push" in c for c in calls)


def test_send_refuses_files_the_viewer_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path, monkeypatch, "x: 1\n")
    calls = _server_file(monkeypatch, "")
    with pytest.raises(server.ServerError, match=r"wiring\.yaml"):
        server.send("kv42", ["wiring.yaml"], yes=True)
    assert calls == []


def _variables(monkeypatch: pytest.MonkeyPatch, stdout: str, code: int = 0) -> list[list[str]]:
    seen: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return subprocess.CompletedProcess(command, code, stdout, "нет доступа")

    monkeypatch.setattr(server.subprocess, "run", run)
    return seen


def test_database_url_is_the_public_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """The private address only resolves inside Railway."""
    seen = _variables(
        monkeypatch,
        "DATABASE_URL=postgresql://u:p@postgres.railway.internal/db\n"
        "DATABASE_PUBLIC_URL=postgresql://u:p=x@proxy.rlwy.net:1234/db\n",
    )
    assert server.database_url("База") == "postgresql://u:p=x@proxy.rlwy.net:1234/db"
    assert seen[0][:4] == ["railway", "variables", "--service", "База"]


def test_database_url_without_a_public_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _variables(monkeypatch, "DATABASE_URL=postgresql://u:p@postgres.railway.internal/db\n")
    with pytest.raises(server.ServerError, match="TCP Proxy"):
        server.database_url()
    _variables(monkeypatch, "", code=1)
    with pytest.raises(server.ServerError, match="нет доступа"):
        server.database_url()


def test_dump_keeps_the_password_out_of_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server.shutil, "which", lambda _: "/usr/bin/docker")
    url = "postgresql://u:секрет@proxy.rlwy.net:1234/db"
    calls: list[dict[str, Any]] = []

    def run(command: list[str], **kw: Any) -> subprocess.CompletedProcess[Any]:
        calls.append({"command": command, **kw})
        if "pg_dump" in " ".join(command):
            kw["stdout"].write(b"PGDMP")
            return subprocess.CompletedProcess(command, 0, None, b"")
        listing = "1; 0 0 TABLE DATA public project u\n2; 0 0 TABLE DATA public firm u\n"
        return subprocess.CompletedProcess(command, 0, listing, "")

    monkeypatch.setattr(server.subprocess, "run", run)
    dest = tmp_path / "x.dump"
    assert server.dump_database(url, dest) == 2
    assert dest.read_bytes() == b"PGDMP" and not (tmp_path / "x.dump.part").exists()
    assert all(url not in " ".join(c["command"]) for c in calls)
    assert calls[0]["env"]["DATABASE_URL"] == url


def test_failed_dump_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda c, **_: subprocess.CompletedProcess(
            c, 1, None, b"Cannot connect to the Docker daemon"
        ),
    )
    with pytest.raises(server.ServerError, match="Docker"):
        server.dump_database("postgresql://x", tmp_path / "x.dump")
    assert list(tmp_path.iterdir()) == []


def test_server_objects_reads_the_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = "12 projects/a/sources/f/plan (1).pdf\n3 feedback/b/c.png\n"
    out = f"шум\n{server.FILE_START}\n{listing}{server.FILE_END}\n"
    monkeypatch.setattr(server, "remote", lambda script, capture=False: out)
    assert server.server_objects() == {
        "projects/a/sources/f/plan (1).pdf": 12,
        "feedback/b/c.png": 3,
    }


def test_missing_skips_files_already_mirrored(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "same").write_bytes(b"123")
    (tmp_path / "a" / "cut").write_bytes(b"1")
    objects = {"a/same": 3, "a/cut": 3, "a/new": 5}
    assert server.missing(objects, tmp_path) == ["a/cut", "a/new"]


def test_batches_stay_under_the_limit() -> None:
    sizes = {"a": 4, "b": 4, "c": 4, "big": 50}
    assert server.batches(["a", "b", "c", "big"], sizes, limit=8) == [["a", "b"], ["c"], ["big"]]
    assert server.batches([], sizes) == []


def test_fetch_unpacks_into_the_mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo("projects/a/sources/f/plan (1).pdf")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"pdf"))
    packed = base64.encodebytes(buf.getvalue()).decode(
        "ascii"
    )  # with line breaks, as base64 prints
    scripts: list[str] = []

    def remote(script: str, capture: bool = False) -> str:
        scripts.append(script)
        return f"{server.FILE_START}\n{packed}{server.FILE_END}\n"

    monkeypatch.setattr(server, "remote", remote)
    server.fetch(["projects/a/sources/f/plan (1).pdf"], tmp_path)
    assert (tmp_path / "projects/a/sources/f/plan (1).pdf").read_bytes() == b"pdf"
    listing = base64.b64encode(b"projects/a/sources/f/plan (1).pdf\n").decode("ascii")
    assert listing in scripts[0] and 'tar -C "$SHTROBA_OBJECTS"' in scripts[0]


def test_backup_dumps_then_fetches_only_new_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "objects" / "a").mkdir(parents=True)
    (tmp_path / "objects" / "a" / "old").write_bytes(b"12")
    fetched: list[list[str]] = []

    def dump(url: str, dest: Path) -> int:
        dest.write_bytes(b"PGDMP")
        return 7

    def fetch(keys: list[str], mirror: Path) -> None:
        fetched.append(keys)
        for key in keys:
            (mirror / key).write_bytes(b"123")

    monkeypatch.setattr(server, "database_url", lambda service: "postgresql://x")
    monkeypatch.setattr(server, "dump_database", dump)
    monkeypatch.setattr(server, "server_objects", lambda: {"a/old": 2, "a/new": 3})
    monkeypatch.setattr(server, "fetch", fetch)
    server.backup(tmp_path)
    assert fetched == [["a/new"]]
    dumps = sorted(p.name for p in (tmp_path / "db").iterdir())
    assert len(dumps) == 2 and dumps[0].endswith("-objects.txt") and dumps[1].endswith(".dump")
    assert (tmp_path / "db" / dumps[0]).read_text(encoding="utf-8") == "3 a/new\n2 a/old\n"


def test_backup_fails_when_a_file_did_not_arrive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "database_url", lambda service: "postgresql://x")

    def dump(url: str, dest: Path) -> int:
        dest.write_bytes(b"PGDMP")
        return 0

    monkeypatch.setattr(server, "dump_database", dump)
    monkeypatch.setattr(server, "server_objects", lambda: {"a/new": 3})
    monkeypatch.setattr(server, "fetch", lambda keys, mirror: None)
    with pytest.raises(server.ServerError, match="не скачались 1"):
        server.backup(tmp_path)


def test_dump_needs_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server.shutil, "which", lambda _: None)
    with pytest.raises(server.ServerError, match="нужен Docker"):
        server.dump_database("postgresql://x", tmp_path / "x.dump")
