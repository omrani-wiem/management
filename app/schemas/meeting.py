from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.meeting import MeetingStatus

SpokenLanguage = Literal["auto", "fr", "en", "ar"]
OutputLanguage = Literal["fr", "en", "ar"]


def parse_timestamp(v) -> Optional[int]:
    """'12:30' -> 750 ; '75:30' -> 4530 ; '1:02:03' -> 3723 ; 90 -> 90 ; invalide -> None"""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return max(0, int(v))
    s = str(v).strip().strip("[]")
    if not s or s.lower() in {"null", "none", "n/a"}:
        return None
    try:
        parts = [int(float(p)) for p in s.split(":")]
    except ValueError:
        return None
    if len(parts) == 1:
        return max(0, parts[0])
    if len(parts) == 2:
        return max(0, parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return max(0, parts[0] * 3600 + parts[1] * 60 + parts[2])
    return None


# ---------- Requêtes / réponses API ----------

class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    participants: Optional[list[str]] = None
    language: SpokenLanguage = "auto"
    output_language: Optional[OutputLanguage] = None


class DecisionOut(BaseModel):
    id: UUID
    text: str
    rationale: Optional[str] = None
    source_seconds: Optional[int] = None

    model_config = {"from_attributes": True}


class SegmentOut(BaseModel):
    idx: int
    start_seconds: float
    end_seconds: float
    text: str

    model_config = {"from_attributes": True}


class MeetingOut(BaseModel):
    id: UUID
    title: str
    status: MeetingStatus
    created_at: Optional[datetime] = None
    participants: Optional[str] = None
    duration_seconds: Optional[int] = None
    language: Optional[str] = None
    output_language: Optional[str] = None

    model_config = {"from_attributes": True}


class MeetingDetail(MeetingOut):
    summary: Optional[str] = None
    raw_text: Optional[str] = None
    decisions: list[DecisionOut] = []


# ---------- Sortie attendue du LLM (validée à chaque appel) ----------

class TaskAnalyzed(BaseModel):
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    confidence: float = 1.0
    priority: str = "medium"
    due_date: Optional[date] = None
    timestamp: Optional[int] = None

    @field_validator("priority", mode="before")
    @classmethod
    def _priority(cls, v):
        v = str(v or "medium").strip().lower()
        return v if v in {"low", "medium", "high"} else "medium"

    @field_validator("assignee", mode="before")
    @classmethod
    def _assignee(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return None if v.lower() in {"", "null", "none", "n/a", "unknown", "inconnu"} else v

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0

    @field_validator("due_date", mode="before")
    @classmethod
    def _due_date(cls, v):
        if v is None or v == "" or str(v).strip().lower() in {"null", "none", "n/a"}:
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v).strip()[:10])
        except ValueError:
            return None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp(cls, v):
        return parse_timestamp(v)


class DecisionAnalyzed(BaseModel):
    text: str
    rationale: Optional[str] = None
    timestamp: Optional[int] = None

    @field_validator("rationale", mode="before")
    @classmethod
    def _rationale(cls, v):
        if v is None:
            return None
        v = str(v).strip()
        return None if v.lower() in {"", "null", "none", "n/a"} else v

    @field_validator("timestamp", mode="before")
    @classmethod
    def _timestamp(cls, v):
        return parse_timestamp(v)


class MeetingAnalysis(BaseModel):
    summary: str
    participants_detected: list[str] = Field(default_factory=list)
    decisions: list[DecisionAnalyzed] = Field(default_factory=list)
    tasks: list[TaskAnalyzed] = Field(default_factory=list)

    @field_validator("participants_detected", "decisions", "tasks", mode="before")
    @classmethod
    def _none_to_list(cls, v):
        return [] if v is None else v

    @field_validator("decisions", mode="before")
    @classmethod
    def _strings_to_decisions(cls, v):
        # certains LLM renvoient ["Décision A", "Décision B"] au lieu d'objets
        if isinstance(v, list):
            return [{"text": x} if isinstance(x, str) else x for x in v]
        return v
