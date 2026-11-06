import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_actor_created", "actor_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    method = Column(String(10), nullable=False)
    endpoint = Column(String(255), nullable=False)
    resource_id = Column(String(36), nullable=True)
    status_code = Column(Integer, nullable=False)
    request_id = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
