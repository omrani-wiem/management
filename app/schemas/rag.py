from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    meeting_id: UUID | None = None          # restreindre la recherche à une réunion
    top_k: int = Field(default=6, ge=1, le=12)


class SourceOut(BaseModel):
    ref: int | None = None                   # numéro [n] cité dans la réponse
    chunk_id: UUID
    meeting_id: UUID
    meeting_title: str
    meeting_date: date | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    timestamp: str | None = None             # "mm:ss" : moment de la réunion
    text: str
    similarity: float                        # similarité cosinus (0 à 1)
    keyword_match: bool = False              # le passage contient aussi un mot de la question


class AskResponse(BaseModel):
    question: str
    answer: str
    answerable: bool                         # False : l'information n'est pas dans les réunions
    sources: list[SourceOut] = []            # uniquement les passages cités par la réponse


class SearchResponse(BaseModel):
    question: str
    results: list[SourceOut]


class RagStatus(BaseModel):
    enabled: bool
    embedding_model: str
    meetings_total: int                      # réunions terminées
    meetings_indexed: int
    chunks_total: int


class ReindexResponse(BaseModel):
    queued: int
