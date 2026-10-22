from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base
import uuid
import datetime


class Team(Base):
    __tablename__ = "teams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", backref="teams_owned")
    members = relationship("TeamMember", back_populates="team", cascade="all, delete-orphan")
    meetings = relationship("Meeting", back_populates="team")


class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255))
    role = Column(String(100))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    team = relationship("Team", back_populates="members")