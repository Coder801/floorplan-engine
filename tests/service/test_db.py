"""Service database on Postgres (tests/service/conftest.py): the migration schema matches the
models; repositories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from floorplan_engine.service import sync
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db import work
from floorplan_engine.service.db import work_records as records
from floorplan_engine.service.db.models import Base, PriceList
from floorplan_engine.service.facts.analysis import Dimension, PageFacts
from tests.service import conftest
from tests.service.conftest import DRAFT, World


@pytest.fixture
def session(db: Session) -> Session:
    return db


def test_schema_has_all_tables() -> None:
    expected = {
        "studio", "app_user", "membership", "studio_profile", "symbol", "project", "source",
        "facts_page", "model_version", "question", "question_revision", "answer_revision",
        "question_thread", "thread_message",
        "build", "build_file", "price_list", "usage", "oauth_account", "user_session",
        "project_member", "invite", "support_grant", "audit_event", "email_code", "login_ticket",
        "access_code", "work_plan", "work_task", "work_line", "work_photo", "work_comment",
        "work_payment", "feedback",
    }  # fmt: skip
    assert set(Base.metadata.tables) == expected


def test_migrations_match_models(pg: Engine) -> None:
    """The schema after migrations is exactly what the models say: a forgotten migration or field
    shows up here.
    """
    with pg.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_source_is_not_added_twice(session: Session) -> None:
    project = repo.create_project(session, repo.create_studio(session, "Студія").id, "Кв 1")
    a = repo.add_source(session, project.id, "plan.pdf", b"%PDF-1", "vector", "src/a")
    b = repo.add_source(session, project.id, "copy.pdf", b"%PDF-1", "vector", "src/b")
    assert a.id == b.id and a.sha256 == repo.sha256(b"%PDF-1")


def test_facts_cache_round_trip(session: Session) -> None:
    project = repo.create_project(session, repo.create_studio(session, "С").id, "Кв")
    source = repo.add_source(session, project.id, "plan.pdf", b"x", "vector", "k")
    assert repo.cached_facts(session, source.id) is None  # not computed yet
    page = PageFacts(
        "plan.pdf", 1, 600, 400, scale=10.0, scale_dims=3,
        dimensions=[Dimension(1000, "h", 300, 50, 150, chain=1, drawn=1000.0, confidence=0.9)],
    )  # fmt: skip
    repo.save_facts(session, source.id, [page])
    assert repo.cached_facts(session, source.id) == [page]


def test_model_versions_increment_and_restore(session: Session) -> None:
    project = repo.create_project(session, repo.create_studio(session, "С").id, "Кв")
    v1 = repo.add_model_version(session, project.id, {"room.yaml": "name: A\n"}, "analyzer")
    v2 = repo.add_model_version(
        session, project.id, {"room.yaml": "name: B\n", "answers.yaml": "answers: {}\n"}, "user"
    )
    assert (v1.version, v2.version) == (1, 2)
    latest = repo.latest_model(session, project.id)
    assert latest is not None and repo.model_files(latest) == {
        "room.yaml": "name: B\n",
        "answers.yaml": "answers: {}\n",
    }
    with pytest.raises(ValueError, match="не файлы модели"):
        repo.add_model_version(session, project.id, {"notes.md": "…"}, "user")


def test_model_version_keeps_text_and_parsed_copy(session: Session) -> None:
    """Every model file goes in as written and comes back byte for byte (comments included);
    the jsonb copy is parsed, and a broken file is kept as text with no copy."""
    project = repo.create_project(session, repo.create_studio(session, "С").id, "Кв")
    files = {
        "room.yaml": "# план\nname: Кухня  # PDF, масштаб\ndate: 2026-10-01\n",
        "plumbing.yaml": "fixtures: []\n",
        "variant.yaml": "mode: economy\n",
        "wiring.yaml": "wires: {}\n",
        "answers.yaml": "answers: [\n",
    }
    version = repo.add_model_version(session, project.id, files, "operator")
    assert repo.model_files(version) == files
    assert version.data["room.yaml"] == {"name": "Кухня", "date": "2026-10-01"}
    assert version.data["variant.yaml"] == {"mode": "economy"}
    assert version.data["answers.yaml"] is None


def test_usage_sums_per_project(session: Session) -> None:
    project = repo.create_project(session, repo.create_studio(session, "С").id, "Кв")
    repo.record_usage(session, project.id, 1, "api", 1.25, input_tokens=1000)
    repo.record_usage(session, project.id, 2, "api", 0.5)
    assert repo.project_cost(session, project.id) == pytest.approx(1.75)


def test_database_url_uses_psycopg(monkeypatch: pytest.MonkeyPatch) -> None:
    from floorplan_engine.service.db.session import database_url

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host:5432/db")
    assert database_url() == "postgresql+psycopg://u:p@host:5432/db"
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/db")  # as Railway gives it
    assert database_url() == "postgresql+psycopg://u:p@host:5432/db"


def test_migration_0023_rounds_money_to_the_cent(pg: Engine, tmp_path: Path) -> None:
    """Money to the cent (decision 2026-11-28): 0023 turns work_line.price into numeric(12, 2),
    rounding half up, and rounds the parsed price list copy in place; downgrade gives a float."""
    with Session(pg) as db:
        world = World(db, tmp_path)
        work.create_plan(db, world.project, world.build, DRAFT, world.owner)
        sync.put_price_list(db, {"studio_id": world.project.studio_id}, "items:\n  a: 1\n")
        db.commit()
    conftest.migrate(pg, "0022", down=True)
    try:
        with pg.begin() as conn:
            kind = "SELECT data_type FROM information_schema.columns WHERE table_name = 'work_line'"
            assert conn.scalar(text(f"{kind} AND column_name = 'price'")) == "double precision"
            conn.execute(text("UPDATE work_line SET price = 76.505 WHERE price = 120"))
            conn.execute(text("UPDATE work_line SET price = 0.225 WHERE price = 15"))
            conn.execute(
                text(
                    "UPDATE price_list SET items = CAST(:items AS jsonb),"
                    " board_kit = CAST(:kit AS jsonb)"
                ),
                {
                    "items": json.dumps({"a": 76.505, "b": {"price": 0.225, "name": "x"}, "c": 5}),
                    "kit": json.dumps([{"name": "k", "price": 1.005}]),
                },
            )
    finally:
        conftest.migrate(pg, "head")
    with pg.connect() as conn:
        assert conn.scalar(text(f"{kind} AND column_name = 'price'")) == "numeric"
        prices = conn.scalars(text("SELECT price FROM work_line ORDER BY price")).all()
        assert [None if p is None else float(p) for p in prices] == [0.23, 34.0, 76.51, None]
        items, kit = conn.execute(text("SELECT items, board_kit FROM price_list")).one()
    assert items == {"a": 76.51, "b": {"price": 0.23, "name": "x"}, "c": 5}
    assert kit == [{"name": "k", "price": 1.01}]


def test_money_is_rounded_on_write(db: Session, tmp_path: Path) -> None:
    """Prices and payments are written to the cent; the parsed price list copy too."""
    world = World(db, tmp_path)
    plan = work.create_plan(db, world.project, world.build, DRAFT, world.owner)
    chases = plan.tasks[0]
    line = chases.lines[0]
    work.edit_line(plan, chases, line, {"price": 0.005}, world.owner)
    db.commit()
    db.refresh(line)
    assert line.price == 0.01
    added = work.add_line(plan, chases, {"title": "Своя", "qty": 3, "price": 0.1}, world.owner)
    db.commit()
    db.refresh(added)
    assert added.price == 0.1 and work.line_sum(added) == 0.3
    with pytest.raises(work.WorkError, match="price: не больше"):
        work.edit_line(plan, chases, line, {"price": 1e11}, world.owner)
    work.plan_action(db, world.project, plan, "propose", world.owner)
    work.plan_action(db, world.project, plan, "approve", world.client)
    pay = {"amount": 0.004, "paid_on": "2026-11-28"}
    with pytest.raises(work.WorkError, match="amount: нужна сумма больше 0"):
        records.add_payment(db, world.project, plan, chases, pay, world.owner)
    paid = records.add_payment(
        db, world.project, plan, chases, {**pay, "amount": 10.005}, world.owner
    )
    assert paid.amount == 10.01
    sync.put_price_list(db, {"studio_id": world.project.studio_id}, "items:\n  a: 76.505\n")
    db.commit()
    assert db.scalar(select(PriceList.items)) == {"a": 76.51}
