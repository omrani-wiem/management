from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from app.models.meeting import MeetingStatus

class MeetingOut(BaseModel):
    id: UUID
    title: str
    status: MeetingStatus
    created_at: datetime

    class Config:
        from_attributes = True


class MeetingDetail(MeetingOut):
    summary: str | None = None
    raw_text: str | None = None