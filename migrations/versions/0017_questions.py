"""questions and answers in their own tables, with revisions

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-17

Decision 2026-11-17 (docs/database.md, «Вопросы и ответы»): the truth about questions and answers
is the database, intake.yaml and answers.yaml are the exchange format at the border. The unused
draft tables round, question and answer (0001) are replaced by question (one per project and qid,
its definition), question_revision (its wording) and answer_revision (its answers). The new tables
are filled from the existing model versions of every project, in version order
(questions.backfill): a change of a question or an answer between versions is a new revision.

The backfill uses the code of its time (service/db/questions.py): if those tables gain columns
later, a database still before 0017 is upgraded by the code of that day — freeze this backfill
here first if it breaks.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from floorplan_engine.service.db import questions

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _author_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("author", sa.String(length=20), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("author_label", sa.String(length=200), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _author_keys() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_version.id"], ondelete="SET NULL"),
    ]


def upgrade() -> None:
    op.drop_table("answer")
    op.drop_table("question")
    op.drop_table("round")
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "question",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("qid", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=True),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("also", jsonb, nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("audience", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("options", jsonb, nullable=False),
        sa.Column("option_labels", jsonb, nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "qid"),
    )
    op.create_table(
        "question_revision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("assumption", jsonb, nullable=True),
        sa.Column("severity", sa.String(length=10), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=20), nullable=False),
        *_author_columns(),
        *_author_keys(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "number"),
    )
    op.create_table(
        "answer_revision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("value", jsonb, nullable=True),
        sa.Column("state", sa.String(length=10), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("log", jsonb, nullable=True),
        *_author_columns(),
        *_author_keys(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "number"),
    )
    session = Session(bind=op.get_bind())
    questions.backfill(session)
    session.flush()
    session.close()


def downgrade() -> None:
    # The revisions are lost; intake.yaml and answers.yaml of every version stay in model_version
    op.drop_table("answer_revision")
    op.drop_table("question_revision")
    op.drop_table("question")
    op.create_table(
        "round",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_version.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "number"),
    )
    op.create_table(
        "question",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("qid", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["round_id"], ["round.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "qid"),
    )
    op.create_table(
        "answer",
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("question_id"),
    )
