"""
Pydantic schemas for SyncJob API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, computed_field

from app.models.models import SyncStatus


class SyncJobResponse(BaseModel):
    """Serialised SyncJob returned by the API."""

    id: int = 0          # populated from job_id in service layer
    job_id: int
    group_id: int
    status: SyncStatus
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    processed_count: int
    new_members_count: int
    error_count: int
    last_cursor: Optional[str]
    error_message: Optional[str]
    created_at: datetime

    # Inject the group's known member_count so the caller can compute progress
    total_member_count: Optional[int] = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def progress_percent(self) -> Optional[float]:
        """Percentage of members processed (None if total is unknown)."""
        if self.total_member_count and self.total_member_count > 0:
            return round(self.processed_count / self.total_member_count * 100, 1)
        return None

    model_config = {"from_attributes": True}


class SyncStartResponse(BaseModel):
    """Returned immediately when a sync job is started."""

    job_id: int
    group_id: int
    status: SyncStatus
    message: str
