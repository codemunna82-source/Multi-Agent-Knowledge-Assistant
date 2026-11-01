"""widen user_mfa.secret for encrypted TOTP seeds

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_mfa") as b:
        b.alter_column("secret", existing_type=sa.String(length=64), type_=sa.String(length=255), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("user_mfa") as b:
        b.alter_column("secret", existing_type=sa.String(length=255), type_=sa.String(length=64), existing_nullable=False)
