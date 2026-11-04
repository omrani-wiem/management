from sqlalchemy import Column, String, DateTime, Date, Integer, ForeignKey, Enum, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import enum
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    __table_args__ = (UniqueConstraint("jira_issue_key", name="uq_tasks_jira_issue_key"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey("meetings.id"), index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    assignee = Column(String(255), nullable=True)
    status = Column(Enum(TaskStatus), default=TaskStatus.todo)
    priority = Column(Enum(TaskPriority), default=TaskPriority.medium)
    created_at = Column(DateTime, default=_utcnow)
    due_date = Column(Date, nullable=True)               # NOUVEAU : échéance
    source_seconds = Column(Integer, nullable=True)      # NOUVEAU : moment de la réunion où la tâche a été dite
    jira_issue_key = Column(String(32), nullable=True)
    jira_issue_url = Column(String(500), nullable=True)
    jira_status = Column(String(100), nullable=True)

    meeting = relationship("Meeting", back_populates="tasks")
