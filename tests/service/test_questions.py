"""Questions and answers in the database (service/db/questions.py): every model version is read
into question rows and revisions, the YAML of a build and of a pull is made from them, a build adds
the code-built questions, and the migration fills the tables from the versions already there."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from floorplan_engine.pipeline import build_project
from floorplan_engine.service import project_store as ps
from floorplan_engine.service import sync
from floorplan_engine.service.db import access as acc
from floorplan_engine.service.db import questions
from floorplan_engine.service.db import repositories as repo
from floorplan_engine.service.db.models import (
    AnswerRevision,
    ModelVersion,
    Project,
    Question,
    QuestionRevision,
)
from floorplan_engine.service.objects import LocalObjectStore
from tests.electrical.test_variants import _project
from tests.service import conftest

INTAKE = """\
# источники
sources:
  - { file: source/plan.pdf }
questions:
  # толщина не подписана
  - { id: q1, stage: plan, target: rooms.r.walls.w2.thickness, text: "Толщина w2?", answer: value }
  - { id: q2, stage: plan, audience: client, text: "Есть обмер?", answer: text, severity: major }
"""
ANSWERS = "answers:\n  q1: 150 # по обмеру\n"


def _project_row(db: Session) -> Project:
    project = repo.create_project(db, repo.create_studio(db, "Искра").id, "Кв")
    project.slug = "kv"
    return project


def _base(tmp_path: Path) -> dict[str, str]:
    folder = _project(tmp_path)
    return {p.name: p.read_text("utf-8") for p in folder.glob("*.yaml")}


def _by_qid(db: Session, project: Project) -> dict[str, questions.Current]:
    return questions.current(db, project.id)


def test_versions_become_revisions(db: Session, tmp_path: Path) -> None:
    project = _project_row(db)
    base = _base(tmp_path)
    first = repo.add_model_version(
        db, project.id, {**base, "intake.yaml": INTAKE, "answers.yaml": ANSWERS}, "analyzer"
    )
    assert (first.intake_yaml, first.answers_yaml) == (INTAKE, ANSWERS)  # the same text
    cur = _by_qid(db, project)
    assert set(cur) == {"q1", "q2"}
    q1, q2 = cur["q1"], cur["q2"]
    assert (q1.row.source, q1.row.position, q1.row.kind) == ("analyzer", 0, "value")
    assert q1.wording is not None and q1.wording.note == "толщина не подписана"
    assert (q1.wording.reason, q1.wording.model_version_id) == ("new", first.id)
    assert q1.answer is not None and q1.answer.value == 150 and q1.answer.state is None
    assert q2.row.audience == "client" and q2.answer is None

    # The same files again: no revisions
    again = repo.add_model_version(db, project.id, repo.model_files(first), "operator")
    assert (
        db.scalar(select(QuestionRevision.id).where(QuestionRevision.model_version_id == again.id))
        is None
    )

    # q1 reworded, q2 gone, q3 new; q1 answered anew, a client text answer to q3, a panel answer
    q3 = '  - { id: q3, stage: plan, audience: client, text: "Где щит?", answer: text,'
    q3 += " severity: minor }"
    lines = INTAKE.replace("Толщина w2?", "Толщина стены w2?").splitlines()
    intake = "\n".join(q3 if "id: q2" in s else s for s in lines) + "\n"
    answers = (
        'answers:\n  q1: 160 # по обмеру\n  q3: { text: "в коридоре" }\n  panel_input: 40\n'
        'log:\n  q3: {"at": "2026-11-17T10:00:00+00:00", "by": "код: Иван"}\n'
    )
    user = acc.oauth_login(db, "google", "u", "u@example.com", True, "Анна")
    third = repo.add_model_version(
        db, project.id, {**base, "intake.yaml": intake, "answers.yaml": answers}, "user", user.id
    )
    assert (third.intake_yaml, third.answers_yaml, third.user_id) == (intake, answers, user.id)
    cur = _by_qid(db, project)
    assert cur["q1"].wording is not None and cur["q1"].wording.reason == "edit"
    assert cur["q1"].wording.text == "Толщина стены w2?" and cur["q1"].wording.number == 2
    assert cur["q2"].row.position is None and cur["q2"].wording is not None
    assert cur["q2"].wording.reason == "removed"
    assert cur["q3"].row.source == "studio" and cur["q3"].row.position == 1
    a3 = cur["q3"].answer
    assert a3 is not None and (a3.state, a3.author, a3.author_label) == (
        "pending",
        "user",
        "код: Иван",
    )
    assert a3.user_id == user.id
    panel = cur["panel_input"]
    assert (panel.row.source, panel.row.position, panel.wording) == ("code", None, None)
    assert panel.answer is not None and panel.answer.value == 40

    # The answer removed, q2 back: a removal revision and a restored question
    fourth = repo.add_model_version(
        db, project.id, {**base, "intake.yaml": INTAKE, "answers.yaml": "answers: {}\n"}, "operator"
    )
    assert fourth.answers_yaml == "answers: {}\n"
    cur = _by_qid(db, project)
    assert cur["q2"].wording is not None and cur["q2"].wording.reason == "restored"
    assert cur["q1"].answer is not None and cur["q1"].answer.value is None
    assert cur["q3"].row.position is None and cur["q3"].wording is not None
    wordings, answers_of_q1 = questions.history(db, cur["q1"].row)
    assert [w.reason for w in wordings] == ["new", "edit", "edit"]
    assert [a.value for a in answers_of_q1] == [150, 160, None]


def test_tables_are_the_truth_of_a_build_and_a_pull(db: Session, tmp_path: Path) -> None:
    """A question changed in the tables (the studio, later in the viewer) reaches the build folder
    and a pull; the rest of intake.yaml stays as it was."""
    store = LocalObjectStore(tmp_path / "store")
    folder = _project(tmp_path)
    (folder / "intake.yaml").write_text(INTAKE, "utf-8")
    (folder / "answers.yaml").write_text(ANSWERS, "utf-8")
    studio = acc.register_firm(
        db, acc.oauth_login(db, "google", "o", "o@example.com", True, "O"), "Искра", "electric"
    )
    project = sync.push(db, store, folder, studio, build=False).project
    q2 = _by_qid(db, project)["q2"]
    assert q2.wording is not None
    db.add(
        QuestionRevision(
            question_id=q2.row.id,
            number=q2.wording.number + 1,
            text="Есть обмерный план?",
            severity="major",
            note="",
            reason="edit",
            author="user",
        )
    )
    db.flush()
    files = ps.project_files(db, project)
    assert files["intake.yaml"].startswith("# источники\nsources:\n")
    assert "Есть обмерный план?" in files["intake.yaml"]
    assert "  # толщина не подписана\n" in files["intake.yaml"]  # the note is written back
    assert files["answers.yaml"] == ANSWERS
    with ps.workdir(db, store, project) as work:
        assert "Есть обмерный план?" in (work / "intake.yaml").read_text("utf-8")
    pulled = tmp_path / "pulled" / "kv"
    sync.pull(db, store, project, pulled)
    assert "Есть обмерный план?" in (pulled / "intake.yaml").read_text("utf-8")
    # An older version gives its own snapshot
    first = db.scalar(select(ModelVersion).where(ModelVersion.project_id == project.id))
    assert first is not None
    assert repo.model_files(first)["intake.yaml"] == INTAKE


def _epd_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_build_records_code_questions_and_matches_the_folder(db: Session, tmp_path: Path) -> None:
    """Push and a build from the database give the same .epd as a build of the folder; the
    code-built questions (panel_…) are written with source code, once."""
    store = LocalObjectStore(tmp_path / "store")
    folder = _project(tmp_path)
    (folder / "intake.yaml").write_text(INTAKE, "utf-8")
    (folder / "answers.yaml").write_text(ANSWERS, "utf-8")
    copy = tmp_path / "copy" / "kv"
    shutil.copytree(folder, copy)
    build_project(copy)
    expected = _epd_digest((copy / "out" / "project.epd").read_bytes())
    studio = acc.register_firm(
        db, acc.oauth_login(db, "google", "o", "o@example.com", True, "O"), "Искра", "electric"
    )
    pushed = sync.push(db, store, folder, studio)
    assert pushed.build is not None
    epd = ps.build_file(db, pushed.build, "project.epd")
    assert epd is not None and _epd_digest(store.get(epd.object_key)) == expected
    cur = _by_qid(db, pushed.project)
    code = {qid: c for qid, c in cur.items() if c.row.source == "code"}
    assert code and all(qid.startswith("panel_") for qid in code)
    assert all(c.row.position is None and c.wording is not None for c in code.values())
    count = db.scalar(text("SELECT count(*) FROM question_revision"))
    rebuilt = ps.build(db, store, pushed.project)
    assert db.scalar(text("SELECT count(*) FROM question_revision")) == count  # nothing new
    epd = ps.build_file(db, rebuilt, "project.epd")
    assert epd is not None and _epd_digest(store.get(epd.object_key)) == expected
    # Code questions never reach intake.yaml
    assert ps.project_files(db, pushed.project)["intake.yaml"] == INTAKE
    # And they follow a change of the report
    report = {"questions": [{"id": "panel_x", "stage": "panel", "text": "A?", "severity": "minor"}]}
    questions.record_code(db, pushed.project.id, None, report)
    questions.record_code(
        db,
        pushed.project.id,
        None,
        {"questions": [{**report["questions"][0], "text": "B?"}, {"id": "q1"}]},
    )
    x = _by_qid(db, pushed.project)["panel_x"]
    assert x.wording is not None and (x.wording.text, x.wording.number) == ("B?", 2)


def _versions_without_tables(db: Session, project: Project, base: dict[str, str]) -> None:
    """Three model versions written as before 0017: no question rows. The third changes q1 by
    the operator, with the log of q2 as it was."""
    answers_2 = (
        'answers:\n  q1: 150\n  q2: { text: "нет", resolved: true }\n'
        'log:\n  q2: {"at": "2026-11-04T10:00:00+00:00", "by": "код: Иван",'
        ' "reviewed_at": "2026-11-05T10:00:00+00:00", "reviewed_by": "Анна"}\n'
    )
    answers_3 = answers_2.replace("q1: 150", "q1: 170")
    for number, answers in ((1, ANSWERS), (2, answers_2), (3, answers_3)):
        db.add(
            ModelVersion(
                project_id=project.id,
                version=number,
                room_yaml=base["room.yaml"],
                electrical_yaml=base["electrical.yaml"],
                intake_yaml=INTAKE,
                answers_yaml=answers,
                data={},
                author="user" if number == 2 else "operator",
            )
        )
        db.flush()


def test_backfill_reads_versions_in_order(db: Session, tmp_path: Path) -> None:
    project = _project_row(db)
    _versions_without_tables(db, project, _base(tmp_path))
    assert questions.backfill(db) == 3
    cur = _by_qid(db, project)
    assert cur["q1"].wording is not None and cur["q1"].wording.author == "operator"
    _, q1 = questions.history(db, cur["q1"].row)
    # "150 # по обмеру" and "150" are the same answer; the log of q2 does not name q1's author
    assert [(a.value, a.author, a.author_label) for a in q1] == [
        (150, "operator", ""),
        (170, "operator", ""),
    ]
    a2 = cur["q2"].answer
    assert a2 is not None and (a2.state, a2.author, a2.author_label) == ("resolved", "user", "Анна")
    assert questions.backfill(db) == 0  # projects with questions are skipped


def test_migration_fills_the_tables(pg: Engine, tmp_path: Path) -> None:
    """Migration 0017 on a database with versions from before it: the tables are filled."""
    base = _base(tmp_path)
    conftest.migrate(pg, "0016", down=True)
    try:
        with Session(pg) as db:
            project = repo.create_project(db, repo.create_studio(db, "С").id, "Кв")
            pid = project.id
            # Only the columns 0016 has
            for number, answers in ((1, ANSWERS), (2, "answers:\n  q1: 160\n")):
                db.execute(
                    text(
                        "INSERT INTO model_version (id, project_id, version, room_yaml,"
                        " intake_yaml, answers_yaml, data, author, created_at)"
                        " VALUES (:id, :p, :v, :room, :intake, :answers, '{}', 'operator', now())"
                    ),
                    {
                        "id": uuid.uuid4(), "p": pid, "v": number, "room": base["room.yaml"],
                        "intake": INTAKE, "answers": answers,
                    },
                )  # fmt: skip
            db.commit()
    finally:
        conftest.migrate(pg, "head")
    with Session(pg) as db:
        cur = questions.current(db, pid)
        assert set(cur) == {"q1", "q2"}
        q1 = cur["q1"].answer
        assert q1 is not None and (q1.value, q1.number) == (160, 2)
        assert db.scalar(select(AnswerRevision.id).where(AnswerRevision.value.is_(None))) is None
        assert db.scalar(select(Question.source).where(Question.qid == "q1")) == "operator"
