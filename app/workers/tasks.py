import os
from celery import Celery
from app.config import settings
from app.database import SessionLocal
from app.models.meeting import Meeting, MeetingStatus
from app.models.transcript import Transcript
from app.models.task import Task, TaskPriority
from app.services.transcription import transcribe_audio
from app.services.ai_processor import analyze_meeting
from app.models.user import User

celery_app = Celery(
    "meeting_ai",
    broker=settings.redis_url,
    backend=settings.redis_url
)

CONFIDENCE_THRESHOLD = 0.75  # en dessous → assignee = null


@celery_app.task(bind=True, max_retries=3)
def process_meeting(self, meeting_id: str, participants: list[str] | None = None):
    db = SessionLocal()

    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"error": "Réunion introuvable"}

        print(f">>> Audio     : {meeting.audio_path}")
        print(f">>> Existe    : {os.path.exists(meeting.audio_path)}")
        print(f">>> Participants saisis : {participants}")

        meeting.status = MeetingStatus.processing
        db.commit()

        # Fusionner participants saisis + users DB (sans doublons)
        db_names = [u.full_name for u in db.query(User).all() if u.full_name]
        all_known = list(dict.fromkeys((participants or []) + db_names))

        # ── ÉTAPE 1 : Transcription Whisper ──────────────────────────
        transcription_result = transcribe_audio(meeting.audio_path, known_names=all_known)
        raw_text = transcription_result["text"]
        print(f">>> Transcription OK ({len(raw_text)} chars)")

        # ── ÉTAPE 2 : Analyse IA unique ──────────────────────────────
        analysis = analyze_meeting(raw_text, known_names=all_known)
        print(f">>> Analyse OK — {len(analysis['tasks'])} tâche(s) trouvée(s)")

        # ── ÉTAPE 3 : Sauvegarde transcript ──────────────────────────
        transcript = Transcript(
            meeting_id=meeting.id,
            raw_text=raw_text,
            summary=analysis["summary"]
        )
        db.add(transcript)

        # ── ÉTAPE 4 : Sauvegarde tâches ──────────────────────────────
        priority_map = {
            "low": TaskPriority.low,
            "medium": TaskPriority.medium,
            "high": TaskPriority.high
        }

        for t in analysis["tasks"]:
            confidence = t.get("confidence", 1.0)
            # Appliquer le seuil de confiance
            assignee = t.get("assignee") if confidence >= CONFIDENCE_THRESHOLD else None

            task = Task(
                meeting_id=meeting.id,
                title=t.get("title", "Tâche sans titre"),
                description=t.get("description"),
                assignee=assignee,
                priority=priority_map.get(t.get("priority", "medium"), TaskPriority.medium)
            )
            db.add(task)
            print(f"    → [{t.get('priority','?').upper()}] {t.get('title')} "
                  f"→ {assignee or 'non assigné'} (conf: {confidence:.2f})")

        # ── ÉTAPE 5 : Mise à jour meeting ─────────────────────────────
        meeting.duration_seconds = transcription_result["duration_seconds"]

        # Fusionner : participants saisis + détectés par l'IA
        ai_detected = analysis.get("participants_detected", [])
        all_participants = list(dict.fromkeys((participants or []) + ai_detected))
        meeting.participants = ", ".join(all_participants) if all_participants else None

        meeting.status = MeetingStatus.done
        db.commit()

        return {
            "status": "done",
            "meeting_id": meeting_id,
            "tasks_count": len(analysis["tasks"]),
            "participants": all_participants
        }

    except Exception as exc:
        db.rollback()
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if meeting:
            meeting.status = MeetingStatus.failed
            db.commit()
        raise self.retry(exc=exc, countdown=10)

    finally:
        db.close()