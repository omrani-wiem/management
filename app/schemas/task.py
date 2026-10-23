from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.task import TaskPriority, TaskStatus


class TaskOut(BaseModel):
    id: UUID
    meeting_id: UUID | None = None
    title: str
    description: str | None = None
    assignee: str | None = None
    status: TaskStatus
    priority: TaskPriority
    created_at: datetime | None = None
    due_date: date | None = None
    source_seconds: int | None = None

    model_config = {"from_attributes": True}


class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    assignee: str | None = None
    priority: TaskPriority | None = None
    due_date: date | None = None
