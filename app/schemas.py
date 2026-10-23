"""Pydantic request/response models."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator


class ActionItemOut(BaseModel):
    id: int
    meeting_id: int
    description: str
    owner: Optional[str] = None
    done: bool


class ActionItemUpdate(BaseModel):
    """PATCH body for /action_items/{id} — all fields optional."""
    done: Optional[bool] = None
    owner: Optional[str] = None
    description: Optional[str] = None

    @field_validator("done", "description")
    @classmethod
    def reject_explicit_null(cls, value):
        # Omission leaves a PATCH field unchanged; explicit null would violate
        # the database's NOT NULL constraints. The owner remains nullable.
        if value is None:
            raise ValueError("This field cannot be null; omit it to leave it unchanged.")
        return value


class MeetingListItem(BaseModel):
    id: int
    title: str
    created_at: datetime
    status: str
    audio_filename: Optional[str] = None


class MeetingDetail(BaseModel):
    id: int
    title: str
    created_at: datetime
    status: str
    audio_filename: Optional[str] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    action_items: List[ActionItemOut] = []


class MeetingCreateResponse(BaseModel):
    id: int
    title: str
    status: str


class HealthResponse(BaseModel):
    status: str
    database: str
