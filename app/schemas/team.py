from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
from datetime import datetime


class TeamMemberCreate(BaseModel):
    full_name: str
    email: Optional[str] = None
    role: Optional[str] = None


class TeamMemberOut(BaseModel):
    id: UUID
    full_name: str
    email: Optional[str] = None
    role: Optional[str] = None

    model_config = {"from_attributes": True}

class TeamCreate(BaseModel):
    name: str

class TeamOut(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    members: list[TeamMemberOut] = []

    model_config = {"from_attributes": True}


class TeamSummary(BaseModel):
    id: UUID
    name: str
    member_count: int

    model_config = {"from_attributes": True}