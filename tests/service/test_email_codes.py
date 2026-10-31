"""Вход по коду на почту (service/db/email_codes.py) на SQLite в памяти: код одноразовый,
действует последний, срок, попытки, частота запросов."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import email_codes as codes
from floorplan_engine.service.db.session import create_tables, make_engine, make_sessions


@pytest.fixture
def db() -> Iterator[Session]:
    engine = make_engine("sqlite://")
    create_tables(engine)
    with make_sessions(engine)() as s:
        yield s


def test_normalize_email() -> None:
    assert codes.normalize_email("  Ann@Example.COM ") == "ann@example.com"
    for bad in ("", "ann", "ann@", "@x.y", "a b@x.y", "ann@host"):
        with pytest.raises(acc.AccessError):
            codes.normalize_email(bad)


def test_code_once_last_one_counts(db: Session) -> None:
    t = acc.now()
    first = codes.issue_code(db, "Ann@example.com", t)
    assert len(first) == 6 and first.isdigit()
    second = codes.issue_code(db, "ann@example.com", t + timedelta(seconds=61))
    if first != second:
        with pytest.raises(acc.AccessError, match="Неверный"):  # прежний больше не действует
            codes.check_code(db, "ann@example.com", first, t + timedelta(seconds=62))
    assert (
        codes.check_code(db, "ANN@example.com", f"{second[:3]} {second[3:]}") == "ann@example.com"
    )
    with pytest.raises(acc.AccessError, match="устарел"):  # погашен
        codes.check_code(db, "ann@example.com", second)


def test_code_expires_and_attempts_end(db: Session) -> None:
    t = acc.now()
    code = codes.issue_code(db, "a@b.cd", t)
    with pytest.raises(acc.AccessError, match="устарел"):
        codes.check_code(db, "a@b.cd", code, t + timedelta(minutes=codes.CODE_MINUTES, seconds=1))
    code = codes.issue_code(db, "x@b.cd", t)
    wrong = "000000" if code != "000000" else "111111"
    for left in range(codes.CODE_ATTEMPTS - 1, 0, -1):
        with pytest.raises(acc.AccessError, match=f"осталось попыток: {left}"):
            codes.check_code(db, "x@b.cd", wrong, t)
    with pytest.raises(acc.AccessError, match="кончились"):
        codes.check_code(db, "x@b.cd", wrong, t)
    with pytest.raises(acc.AccessError, match="устарел"):  # и верный уже не примет
        codes.check_code(db, "x@b.cd", code, t)


def test_resend_limits(db: Session) -> None:
    t = acc.now()
    codes.issue_code(db, "a@b.cd", t)
    with pytest.raises(codes.TooSoonError) as soon:
        codes.issue_code(db, "a@b.cd", t + timedelta(seconds=10))
    assert 0 < soon.value.seconds <= codes.CODE_RESEND_SECONDS
    for k in range(1, codes.CODE_PER_HOUR):
        codes.issue_code(db, "a@b.cd", t + timedelta(minutes=2 * k))
    with pytest.raises(codes.TooSoonError, match="Слишком много"):
        codes.issue_code(db, "a@b.cd", t + timedelta(minutes=20))
    codes.issue_code(db, "a@b.cd", t + timedelta(minutes=61))  # час прошёл
    codes.issue_code(db, "other@b.cd", t + timedelta(minutes=20))  # другой адрес — свой счёт
