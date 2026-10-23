from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TeamMemberCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    role: str | None = Field(default=None, max_length=100)


class TeamMemberOut(BaseModel):
    id: UUID
    full_name: str
    email: str | None = None
    role: str | None = None

    model_config = {"from_attributes": True}


class TeamMemberWithCount(TeamMemberOut):
    team_id: UUID
    task_count: int = 0


class TeamOut(BaseModel):
    id: UUID
    name: str
    members: list[TeamMemberOut] = []

    model_config = {"from_attributes": True}


class TeamSummary(BaseModel):
    id: UUID
    name: str
    member_count: int
