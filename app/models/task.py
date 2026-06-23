from  sqlalchemy import Column, String, DateTime, ForeignKey, Enum, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import enum

class TaskStatus(str, enum.Enum):
    todo = "todo"
    in_progress = "in_progress"
    done = "done"

class TaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"

class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id  = Column(UUID(as_uuid=True), ForeignKey("meetings.id"))
    title       = Column(String(255), nullable=False)
    description = Column(Text)
    assignee    = Column(String(255), nullable=True)
    status      = Column(Enum(TaskStatus), default=TaskStatus.todo)
    priority    = Column(Enum(TaskPriority), default=TaskPriority.medium)

    meeting = relationship("Meeting", back_populates="tasks")