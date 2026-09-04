"""Add authorized Telegram message and media metadata tables."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("telegram_message_id", sa.Integer(), nullable=False),
        sa.Column("author_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("message_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "telegram_message_id", name="uq_messages_group_message"),
    )
    op.create_index("ix_messages_group_id", "telegram_messages", ["group_id"])
    op.create_index("ix_messages_date", "telegram_messages", ["message_date"])

    op.create_table(
        "telegram_media",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("media_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("media_type", sa.Enum("photo", "video", "document", "audio", "voice", "sticker", "other", name="media_type_enum"), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("remote_reference", sa.String(length=255), nullable=True),
        sa.Column("local_path", sa.String(length=1024), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("download_status", sa.Enum("not_requested", "pending", "downloaded", "rejected", "failed", name="media_download_status_enum"), nullable=False, server_default="not_requested"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["telegram_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", "media_index", name="uq_media_message_index"),
    )
    op.create_index("ix_media_type", "telegram_media", ["media_type"])
    op.create_index("ix_media_download_status", "telegram_media", ["download_status"])


def downgrade() -> None:
    op.drop_table("telegram_media")
    op.drop_table("telegram_messages")
    op.execute("DROP TYPE IF EXISTS media_download_status_enum")
    op.execute("DROP TYPE IF EXISTS media_type_enum")