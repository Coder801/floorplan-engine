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
