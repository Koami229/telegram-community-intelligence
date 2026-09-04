"""
SQLAlchemy models — User, Group, GroupMember, SyncJob.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.audit import AuthorizationAudit


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class GroupType(str, enum.Enum):
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"
    UNKNOWN = "unknown"


class MemberStatus(str, enum.Enum):
    MEMBER = "member"
    ADMIN = "admin"
    CREATOR = "creator"
    RESTRICTED = "restricted"
    LEFT = "left"
    KICKED = "kicked"
    UNKNOWN = "unknown"


class SyncStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class MediaType(str, enum.Enum):
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    VOICE = "voice"
    STICKER = "sticker"
    OTHER = "other"


class MediaDownloadStatus(str, enum.Enum):
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    DOWNLOADED = "downloaded"
    REJECTED = "rejected"
    FAILED = "failed"


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    """Represents a Telegram user observed in at least one monitored group."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        Index("ix_users_username", "username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    profile_photo_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    memberships: Mapped[List["GroupMember"]] = relationship(
        "GroupMember", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User telegram_id={self.telegram_id} username={self.username!r}>"


class Group(Base):
    """Represents a Telegram group/channel being monitored."""

    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("telegram_group_id", name="uq_groups_telegram_group_id"),
        Index("ix_groups_username", "username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    group_type: Mapped[GroupType] = mapped_column(
        Enum(GroupType, name="group_type_enum", values_callable=lambda objs: [e.value for e in objs]),
        default=GroupType.UNKNOWN,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    collection_authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    collection_authorized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    member_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    media_download_authorized: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    first_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    members: Mapped[List["GroupMember"]] = relationship(
        "GroupMember", back_populates="group", cascade="all, delete-orphan"
    )
    sync_jobs: Mapped[List["SyncJob"]] = relationship(
        "SyncJob", back_populates="group", cascade="all, delete-orphan"
    )
    messages: Mapped[List["TelegramMessage"]] = relationship(
        "TelegramMessage", back_populates="group", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Group telegram_group_id={self.telegram_group_id} title={self.title!r}>"


class GroupMember(Base):
    """Join table: a User's membership in a Group, with lifecycle tracking."""

    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
        Index("ix_group_members_group_id", "group_id"),
        Index("ix_group_members_user_id", "user_id"),
        Index("ix_group_members_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[MemberStatus] = mapped_column(
        Enum(MemberStatus, name="member_status_enum", values_callable=lambda objs: [e.value for e in objs]),
        default=MemberStatus.MEMBER,
        nullable=False,
    )

    first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    group: Mapped["Group"] = relationship("Group", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="memberships")

    def __repr__(self) -> str:
        return f"<GroupMember group_id={self.group_id} user_id={self.user_id} status={self.status}>"


class SyncJob(Base):
    """Tracks the progress and state of a member-synchronisation job."""

    __tablename__ = "sync_jobs"
    __table_args__ = (
        Index("ix_sync_jobs_group_id", "group_id"),
        Index("ix_sync_jobs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status_enum", values_callable=lambda objs: [e.value for e in objs]),
        default=SyncStatus.PENDING,
        nullable=False,
    )

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_members_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_cursor: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    group: Mapped["Group"] = relationship("Group", back_populates="sync_jobs")

    def __repr__(self) -> str:
        status_val = self.status.value if isinstance(self.status, SyncStatus) else self.status
        return f"<SyncJob id={self.id} group_id={self.group_id} status={status_val}>"


class TelegramMessage(Base):
    """Metadata for a message observed through an authorized Telegram session."""

    __tablename__ = "telegram_messages"
    __table_args__ = (
        UniqueConstraint("group_id", "telegram_message_id", name="uq_messages_group_message"),
        Index("ix_messages_group_id", "group_id"),
        Index("ix_messages_date", "message_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False
    )
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    author_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    group: Mapped["Group"] = relationship("Group", back_populates="messages")
    media: Mapped[List["TelegramMedia"]] = relationship(
        "TelegramMedia", back_populates="message", cascade="all, delete-orphan"
    )


class TelegramMedia(Base):
    """Metadata and optional local storage reference for message media."""

    __tablename__ = "telegram_media"
    __table_args__ = (
        UniqueConstraint("message_id", "media_index", name="uq_media_message_index"),
        Index("ix_media_type", "media_type"),
        Index("ix_media_download_status", "download_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("telegram_messages.id", ondelete="CASCADE"), nullable=False
    )
    media_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    media_type: Mapped[MediaType] = mapped_column(
        Enum(MediaType, name="media_type_enum", values_callable=lambda objs: [e.value for e in objs]),
        nullable=False,
    )
    file_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    remote_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    local_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    download_status: Mapped[MediaDownloadStatus] = mapped_column(
        Enum(MediaDownloadStatus, name="media_download_status_enum", values_callable=lambda objs: [e.value for e in objs]),
        default=MediaDownloadStatus.NOT_REQUESTED,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    message: Mapped["TelegramMessage"] = relationship("TelegramMessage", back_populates="media")
