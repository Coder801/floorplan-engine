"""File storage by key (service/objects.py): safe keys, write and read back, delete by prefix."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from floorplan_engine.service.objects import (
    LocalObjectStore,
    ObjectKeyError,
    build_key,
    check_key,
    safe_name,
    source_key,
)


@pytest.mark.parametrize("key", ["", "/abs", "a//b", "a/../b", "../x", "a/./b", "a\\\\b", "a/b:c"])
def test_unsafe_keys_are_refused(key: str) -> None:
    with pytest.raises(ObjectKeyError):
        check_key(key)


def test_keys_of_sources_and_builds() -> None:
    pid, bid = uuid.uuid4(), uuid.uuid4()
    assert safe_name("../План кв 42, ред.2.pdf") == "План кв 42_ ред.2.pdf"
    assert safe_name("...") == "file"
    assert source_key(pid, "ab12", "dir/План.pdf") == f"projects/{pid}/sources/ab12/План.pdf"
    assert build_key(pid, bid, "out/project.epd").endswith(f"{bid}/out/project.epd")


def test_local_store_round_trip(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    store.put("projects/p/builds/b/out/report.md", b"# report")
    store.put("projects/p/sources/s/plan.pdf", b"%PDF")
    assert store.get("projects/p/builds/b/out/report.md") == b"# report"
    assert store.exists("projects/p/sources/s/plan.pdf")
    assert (
        store.local_path("projects/p/sources/s/plan.pdf")
        == tmp_path / "projects/p/sources/s/plan.pdf"
    )
    assert store.local_path("projects/p/none") is None
    assert not any(p.name.endswith(".tmp") for p in tmp_path.rglob("*"))  # no half-written files
    store.delete_prefix("projects/p/builds/b")
    assert not store.exists("projects/p/builds/b/out/report.md")
    assert store.exists("projects/p/sources/s/plan.pdf")
    with pytest.raises(FileNotFoundError):
        store.get("projects/p/builds/b/out/report.md")
