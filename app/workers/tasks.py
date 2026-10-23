import logging
import uuid

from celery import Celery

from app.config import settings
from app.database import SessionLocal
from app.models.meeting import Meeting, MeetingStatus
from app.models.transcript import Transcript
from app.services.ai_processor import analyze_meeting
from app.services.meeting_pipeline import (
    get_known_names,
    merge_names,
    resolve_output_language,
    resolve_spoken_language,
    save_analysis,
    save_segments,
    save_transcript,
    transcript_for_llm,
)
from app.services.transcription import transcribe_audio

logger = logging.getLogger(__name__)

celery_app = Celery("meeting_ai", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"])


def _mark_failed(db, meeting_id: str) -> None:
    db.rollback()
    meeting = db.get(Meeting, uuid.UUID(meeting_id))
    if meeting is not None:
        meeting.status = MeetingStatus.failed
        db.commit()


@celery_app.task(bind=True, max_retries=3)
def process_meeting(self, meeting_id: str, participants: list[str] | None = None):
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, uuid.UUID(meeting_id))
        if meeting is None:
            logger.error("Réunion %s introuvable", meeting_id)
            return {"error": "Réunion introuvable"}

        meeting.status = MeetingStatus.processing
        db.commit()

        known_names = merge_names(participants or [], get_known_names(db, meeting))

        # Étape 1 : transcription (sautée si elle a déjà été sauvegardée lors d'un essai précédent)
        transcript = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).first()
        if transcript is None:
            result = transcribe_audio(
                meeting.audio_path,
                known_names=known_names,
                language=resolve_spoken_language(meeting),  # None = détection automatique
            )
            if not result["text"]:
                logger.warning("Transcription vide pour %s", meeting_id)
                _mark_failed(db, meeting_id)
                return {"error": "Aucune parole détectée"}
            save_transcript(
                db, meeting, result["text"], result["duration_seconds"], language=result["language"]
            )
            save_segments(db, meeting, result["segments"])
            raw_text = result["text"]
        else:
            raw_text = transcript.raw_text

        # Étape 2 : analyse LLM (seule étape rejouée si elle échoue)
        llm_text = transcript_for_llm(db, meeting, raw_text)   # avec marqueurs [mm:ss]
        analysis = analyze_meeting(
            llm_text,
            known_names,
            resolve_output_language(meeting),
            meeting.created_at.date() if meeting.created_at else None,
        )
        saved = save_analysis(
            db, meeting, analysis,
            typed_participants=participants or meeting.participants_list,
        )
        logger.info(
            "Réunion %s traitée : %d tâches, %d décisions",
            meeting_id, len(saved["tasks"]), len(saved["decisions"]),
        )
        return {"status": "done", "tasks": len(saved["tasks"]), "decisions": len(saved["decisions"])}

    except FileNotFoundError:
        logger.exception("Fichier audio manquant pour %s", meeting_id)
        _mark_failed(db, meeting_id)
        return {"error": "Fichier audio introuvable"}
    except Exception as exc:
        db.rollback()
        logger.exception("Échec du traitement de %s (essai %d)", meeting_id, self.request.retries + 1)
        if self.request.retries >= self.max_retries:
            _mark_failed(db, meeting_id)
            raise
        raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1))
    finally:
        db.close()
