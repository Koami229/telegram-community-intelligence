"""Add audit records for authorization decisions."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authorization_audits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("collection_authorized", sa.Boolean(), nullable=False),
        sa.Column("media_download_authorized", sa.Boolean(), nullable=False),
        sa.Column("actor_label", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_authorization_audits_group_id", "authorization_audits", ["group_id"])


def downgrade() -> None:
    op.drop_table("authorization_audits")