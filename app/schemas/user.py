from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt ne gère que 72 octets
    full_name: str = Field(min_length=1, max_length=255)


class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: str

    model_config = {"from_attributes": True}
