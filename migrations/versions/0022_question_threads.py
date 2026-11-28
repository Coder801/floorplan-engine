"""question threads

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-28

Decision 2026-11-28 (docs/question-threads.md, step 1; docs/database.md, «Вопросы и ответы»): a
question is discussed in a thread (question_thread) of messages (thread_message); the studio
accepts a message as the answer. One open or checking thread per question. The threads are filled
from the answers already there (threads.backfill): a text answer — a thread with a message of its
author, the `returned` comment — a second message of the studio, `resolved` — the thread resolved;
a form answer — a resolved thread without messages; a question without answers — an open thread.
intake.yaml and answers.yaml made from the tables do not change.

The backfill uses the code of its time (service/db/threads.py, and access.project_role for the
role of an author): if those tables gain columns later, a database still before 0022 is upgraded
by the code of that day — freeze this backfill here first if it breaks.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from floorplan_engine.service.db import threads

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "question_thread",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("previous_thread_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("accepted_message_id", sa.Uuid(), nullable=True),
        sa.Column("result_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["question.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["previous_thread_id"], ["question_thread.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["result_version_id"], ["model_version.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_question_thread_live",
        "question_thread",
        ["question_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('open', 'checking')"),
    )
    op.create_index("ix_question_thread_project", "question_thread", ["project_id", "created_at"])
    op.create_table(
        "thread_message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("author", sa.String(length=10), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("author_label", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["thread_id"], ["question_thread.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_thread_message_thread", "thread_message", ["thread_id", "created_at"])
    op.create_foreign_key(
        "fk_question_thread_accepted_message",
        "question_thread",
        "thread_message",
        ["accepted_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    session = Session(bind=op.get_bind())
    threads.backfill(session)
    session.flush()
    session.close()


def downgrade() -> None:
    # The threads and their messages are lost; the answers stay in answer_revision. A follow-up
    # question (threads.follow_up) stays a question, its predecessor keeps reason `superseded`
    op.drop_constraint("fk_question_thread_accepted_message", "question_thread", type_="foreignkey")
    op.drop_index("ix_thread_message_thread", table_name="thread_message")
    op.drop_table("thread_message")
    op.drop_index("ix_question_thread_project", table_name="question_thread")
    op.drop_index("uq_question_thread_live", table_name="question_thread")
    op.drop_table("question_thread")
