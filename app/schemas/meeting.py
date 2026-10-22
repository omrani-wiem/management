from typing import Optional
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from app.models.meeting import MeetingStatus



class TaskAnalyzed(BaseModel):
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    priority: str = "medium"

class MeetingAnalysis(BaseModel):
    summary: str
    participants_detected: list[str] = []
    tasks: list[TaskAnalyzed] = []

class MeetingOut(BaseModel):
    id: UUID
    title: str
    status: MeetingStatus
    created_at: datetime
    participants: Optional[str] = None
    duration_seconds: Optional[int] = None

    model_config = {"from_attributes": True}

class MeetingDetail(MeetingOut):
    summary: Optional[str] = None
    raw_text: Optional[str] = None

class MeetingCreate(BaseModel):
    title: str