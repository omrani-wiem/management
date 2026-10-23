from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import uuid
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Decision(Base):
    """Décision prise pendant une réunion (distincte d'une tâche à faire)."""
    __tablename__ = "decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id = Column(UUID(as_uuid=True), ForeignKey("meetings.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    rationale = Column(Text, nullable=True)
    source_seconds = Column(Integer, nullable=True)   # moment de la réunion (en secondes)
    created_at = Column(DateTime, default=_utcnow)
