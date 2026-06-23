from pydantic import BaseModel
from uuid import UUID
from app.models.task import TaskStatus, TaskPriority


class TaskOut(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    assignee: str | None
    status: TaskStatus
    priority: TaskPriority

    class Config:
        from_attributes = True

class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    assignee: str | None = None