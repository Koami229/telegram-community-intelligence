"""Schemas for collection authorization and its audit trail."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CollectionAuthorizationRequest(BaseModel):
    confirmed: bool
    media_download_confirmed: bool = False
    reason: Optional[str] = Field(default=None, max_length=2000)


class AuthorizationAuditResponse(BaseModel):
    id: int
    group_id: int
    collection_authorized: bool
    media_download_authorized: bool
    actor_label: Optional[str]
    reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}