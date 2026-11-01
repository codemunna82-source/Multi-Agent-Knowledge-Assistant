"""AI Learning Academy: progress, quiz attempts, exercises, activity, projects

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("academy_progress",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False), sa.Column("lesson_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("step", sa.Integer(), nullable=False), sa.Column("bookmarked", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "lesson_id", name="uq_academy_progress"))
    op.create_index("ix_academy_progress_user_id", "academy_progress", ["user_id"])
    op.create_table("academy_quiz_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False), sa.Column("lesson_id", sa.String(64), nullable=False), sa.Column("question_id", sa.String(96), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_academy_quiz_attempts_user_id", "academy_quiz_attempts", ["user_id"])
    op.create_table("academy_exercises",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False), sa.Column("lesson_id", sa.String(64), nullable=False), sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "lesson_id", "kind", name="uq_academy_exercise"))
    op.create_index("ix_academy_exercises_user_id", "academy_exercises", ["user_id"])
    op.create_table("academy_activity",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False), sa.Column("day", sa.String(10), nullable=False), sa.Column("count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "day", name="uq_academy_activity"))
    op.create_index("ix_academy_activity_user_id", "academy_activity", ["user_id"])
    op.create_table("academy_projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False), sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("done_steps", sa.JSON(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "project_id", name="uq_academy_project"))
    op.create_index("ix_academy_projects_user_id", "academy_projects", ["user_id"])


def downgrade() -> None:
    for t in ("academy_projects", "academy_activity", "academy_exercises", "academy_quiz_attempts", "academy_progress"):
        op.drop_table(t)
