import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth_utils import get_current_user
from app.config import settings
from app.database import get_db
from app.models.chunk import MeetingChunk
from app.models.meeting import Meeting, MeetingStatus
from app.models.user import User
from app.schemas.rag import AskRequest, AskResponse, RagStatus, ReindexResponse, SearchResponse
from app.services import rag
from app.workers.tasks import index_meeting_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rag", tags=["rag"])


def _require_enabled() -> None:
    if not settings.rag_enabled:
        raise HTTPException(status_code=503, detail="La recherche RAG est désactivée (RAG_ENABLED=false)")


def _owned_meeting(db: Session, meeting_id: UUID, user: User) -> Meeting:
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id, Meeting.owner_id == user.id).first()
    if not meeting:
        raise HTTPException(status_code=404, detail="Réunion introuvable")
    return meeting


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Pose une question sur tes réunions : réponse AVEC citations (réunion, minute, extrait).
    Si l'information n'y est pas, `answerable` vaut false et aucune source n'est renvoyée."""
    _require_enabled()
    if payload.meeting_id:
        _owned_meeting(db, payload.meeting_id, current_user)
    try:
        result = rag.answer_question(
            db, current_user.id, payload.question, meeting_id=payload.meeting_id, top_k=payload.top_k
        )
    except rag.RAGError:
        logger.exception("RAG : réponse invalide du LLM")
        raise HTTPException(status_code=502, detail="Le LLM n'a pas produit de réponse valide. Réessaie.")
    except Exception:
        logger.exception("RAG : erreur pendant la recherche")
        raise HTTPException(status_code=503, detail="Recherche indisponible (modèle d'embedding ou LLM).")
    return AskResponse(question=payload.question, **result)


@router.post("/search", response_model=SearchResponse)
def search(payload: AskRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Recherche seule (sans LLM) : les passages les plus proches, avec leur similarité."""
    _require_enabled()
    if payload.meeting_id:
        _owned_meeting(db, payload.meeting_id, current_user)
    try:
        results = rag.search_chunks(
            db, current_user.id, payload.question, meeting_id=payload.meeting_id, top_k=payload.top_k
        )
    except Exception:
        logger.exception("RAG : erreur pendant la recherche")
        raise HTTPException(status_code=503, detail="Recherche indisponible (modèle d'embedding).")
    return SearchResponse(question=payload.question, results=results)


@router.get("/status", response_model=RagStatus)
def status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    total = (
        db.query(func.count(Meeting.id))
        .filter(Meeting.owner_id == current_user.id, Meeting.status == MeetingStatus.done)
        .scalar()
    )
    indexed = chunks = 0
    if settings.rag_enabled:
        indexed = (
            db.query(func.count(func.distinct(MeetingChunk.meeting_id)))
            .filter(MeetingChunk.owner_id == current_user.id)
            .scalar()
        )
        chunks = db.query(func.count(MeetingChunk.id)).filter(MeetingChunk.owner_id == current_user.id).scalar()
    return RagStatus(
        enabled=settings.rag_enabled, embedding_model=settings.embedding_model,
        meetings_total=total, meetings_indexed=indexed, chunks_total=chunks,
    )


def _enqueue(meeting_ids: list) -> None:
    try:
        for mid in meeting_ids:
            index_meeting_task.delay(str(mid))
    except Exception:
        logger.exception("Impossible d'envoyer l'indexation au worker")
        raise HTTPException(status_code=503, detail="File de traitement indisponible (Redis/Celery).")


@router.post("/reindex", response_model=ReindexResponse, status_code=202)
def reindex_all(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """(Ré)indexe toutes tes réunions terminées : à lancer une fois pour les réunions antérieures au RAG."""
    _require_enabled()
    ids = [
        m.id for m in db.query(Meeting.id)
        .filter(Meeting.owner_id == current_user.id, Meeting.status == MeetingStatus.done)
    ]
    _enqueue(ids)
    return ReindexResponse(queued=len(ids))


@router.post("/reindex/{meeting_id}", response_model=ReindexResponse, status_code=202)
def reindex_one(meeting_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_enabled()
    meeting = _owned_meeting(db, meeting_id, current_user)
    _enqueue([meeting.id])
    return ReindexResponse(queued=1)
