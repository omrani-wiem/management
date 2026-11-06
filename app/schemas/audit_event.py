from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: UUID
    method: str
    endpoint: str
    resource_id: str | None = None
    status_code: int
    request_id: str
    created_at: datetime

    model_config = {"from_attributes": True}
