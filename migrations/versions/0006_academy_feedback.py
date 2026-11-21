"""AI Learning Academy: lesson feedback

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("academy_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False), sa.Column("lesson_id", sa.String(64), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False), sa.Column("step", sa.String(24), nullable=True), sa.Column("comment", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_academy_feedback_user_id", "academy_feedback", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_academy_feedback_user_id", table_name="academy_feedback")
    op.drop_table("academy_feedback")
