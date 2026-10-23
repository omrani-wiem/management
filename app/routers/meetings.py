import logging
import os
import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.auth_utils import get_current_user
from app.config import settings
from app.database import get_db
from app.models.decision import Decision
from app.models.meeting import Meeting, MeetingStatus
from app.models.segment import TranscriptSegment
from app.models.user import User
from app.schemas.meeting import (
    DecisionOut,
    MeetingCreate,
    MeetingDetail,
    MeetingOut,
    SegmentOut,
)
from app.workers.tasks import process_meeting

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/meetings", tags=["meetings"])

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXT = {".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg"}
SPOKEN_LANGUAGES = {"auto", "fr", "en", "ar"}
OUTPUT_LANGUAGES = {"fr", "en", "ar"}
READ_CHUNK = 1024 * 1024
MAX_BYTES = settings.max_upload_mb * 1024 * 1024


def _looks_like_audio(h: bytes) -> bool:
    """Vérifie les premiers octets (le content-type envoyé par le client n'est pas fiable)."""
    if len(h) < 12:
        return False
    return (
        h.startswith(b"ID3")                           # mp3 avec tag
        or (h[0] == 0xFF and (h[1] & 0xE0) == 0xE0)    # mp3 brut
        or (h[:4] == b"RIFF" and h[8:12] == b"WAVE")   # wav
        or h[4:8] == b"ftyp"                           # m4a / mp4
        or h[:4] == b"\x1a\x45\xdf\xa3"                # webm / mkv
        or h[:4] == b"OggS"                            # ogg
    )


def _parse_participants(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _check_languages(language: Optional[str], output_language: Optional[str]) -> tuple[str, Optional[str]]:
    language = (language or "auto").strip().lower()
    if language not in SPOKEN_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"language doit être parmi : {sorted(SPOKEN_LANGUAGES)}")
    out = (output_language or "").strip().lower() or None
    if out is not None and out not in OUTPUT_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"output_language doit être parmi : {sorted(OUTPUT_LANGUAGES)}")
    return language, out


def _get_owned_meeting(db: Session, meeting_id: UUID, user: User) -> Meeting:
    meeting = (
        db.query(Meeting)
        .filter(Meeting.id == meeting_id, Meeting.owner_id == user.id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Réunion introuvable")
    return meeting


@router.post("/upload", response_model=MeetingOut)
async def upload_meeting(
    title: str = Form(..., min_length=1, max_length=255),
    file: UploadFile = File(...),
    participants: Optional[str] = Form(None),
    language: str = Form("auto"),
    output_language: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    language, output_language = _check_languages(language, output_language)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporté. Formats acceptés : {', '.join(sorted(ALLOWED_EXT))}",
        )

    header = await file.read(16)
    if not _looks_like_audio(header):
        raise HTTPException(status_code=400, detail="Le fichier n'est pas un audio valide")

    # Nom de fichier généré côté serveur : on n'utilise jamais file.filename dans le chemin
    filepath = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{ext}")
    size = len(header)
    try:
        with open(filepath, "wb") as out:
            out.write(header)
            while chunk := await file.read(READ_CHUNK):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Fichier trop volumineux (max {settings.max_upload_mb} Mo)",
                    )
                out.write(chunk)
    except Exception:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise

    participants_list = _parse_participants(participants)
    meeting = Meeting(
        title=title.strip(),
        audio_path=filepath,
        status=MeetingStatus.pending,
        owner_id=current_user.id,
        participants=", ".join(participants_list) if participants_list else None,
        language=None if language == "auto" else language,
        output_language=output_language,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    try:
        process_meeting.delay(str(meeting.id), participants_list)
    except Exception:
        logger.exception("Impossible d'envoyer la réunion %s au worker", meeting.id)
        meeting.status = MeetingStatus.failed
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="File de traitement indisponible (Redis/Celery). Réessaie plus tard.",
        )
    return meeting


@router.post("/create", response_model=MeetingOut)
def create_live_meeting(
    payload: MeetingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    participants_list = [p.strip() for p in (payload.participants or []) if p.strip()]
    meeting = Meeting(
        title=payload.title.strip(),
        status=MeetingStatus.pending,
        owner_id=current_user.id,
        participants=", ".join(participants_list) if participants_list else None,
        language=None if payload.language == "auto" else payload.language,
        output_language=payload.output_language,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.get("/", response_model=list[MeetingOut])
def list_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Meeting)
        .filter(Meeting.owner_id == current_user.id)
        .order_by(Meeting.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{meeting_id}", response_model=MeetingDetail)
def get_meeting(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    meeting = _get_owned_meeting(db, meeting_id, current_user)

    result = MeetingDetail.model_validate(meeting)
    if meeting.transcript:
        result.summary = meeting.transcript.summary
        result.raw_text = meeting.transcript.raw_text
    decisions = (
        db.query(Decision)
        .filter(Decision.meeting_id == meeting.id)
        .order_by(Decision.created_at)
        .all()
    )
    result.decisions = [DecisionOut.model_validate(d) for d in decisions]
    return result


@router.get("/{meeting_id}/segments", response_model=list[SegmentOut])
def get_segments(
    meeting_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Transcription découpée et horodatée."""
    meeting = _get_owned_meeting(db, meeting_id, current_user)
    return (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.meeting_id == meeting.id)
        .order_by(TranscriptSegment.idx)
        .all()
    )
