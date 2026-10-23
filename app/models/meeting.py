from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import datetime
import enum


class MeetingStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=True)
    title = Column(String(255), nullable=False)
    status = Column(Enum(MeetingStatus), default=MeetingStatus.pending)
    audio_path = Column(String(500))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    duration_seconds = Column(Integer, nullable=True)
    participants = Column(String(1000), nullable=True)
    language = Column(String(10), nullable=True)          # NOUVEAU : langue parlée (fr / en / ar...), choisie ou détectée
    output_language = Column(String(10), nullable=True)   # NOUVEAU : langue du résumé, des décisions et des tâches

    owner = relationship("User", back_populates="meetings")
    team = relationship("Team", back_populates="meetings")
    transcript = relationship("Transcript", back_populates="meeting", uselist=False)
    tasks = relationship("Task", back_populates="meeting")

    @property
    def duration_minutes(self) -> int | None:
        if self.duration_seconds is None:
            return None
        return round(self.duration_seconds / 60)

    @property
    def participants_list(self) -> list[str]:
        if not self.participants:
            return []
        return [p.strip() for p in self.participants.split(",") if p.strip()]
