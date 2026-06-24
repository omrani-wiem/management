import os

from celery import Celery
from app.config import settings
from app.database import SessionLocal
from app.models.meeting import Meeting, MeetingStatus
from app.models.transcript import Transcript
from app.models.task import Task, TaskPriority
from app.services.transcription import transcribe_audio
from app.services.ai_processor import summarize_transcript, extract_tasks

celery_app = Celery(
    "meeting_ai",
    broker=settings.redis_url,
    backend=settings.redis_url
)

@celery_app.task(bind=True, max_retries=3)
def process_meeting(self, meeting_id: str):
    """
    Tâche principale : transcription → résumé → extraction tâches
    """
    db = SessionLocal()

    try:
       
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"error": "Réunion introuvable"}
        
        #je vais ajouter juste pour verifier chemin
        print(f">>> Chemin audio : {meeting.audio_path}")
        print(f">>> Fichier existe : {os.path.exists(meeting.audio_path)}")

        
        meeting.status = MeetingStatus.processing
        db.commit()

       
        transcription_result = transcribe_audio(meeting.audio_path)
        raw_text = transcription_result["text"]

      
        summary = summarize_transcript(raw_text)

       
        extracted_tasks = extract_tasks(raw_text)

      
        transcript = Transcript(
            meeting_id=meeting.id,
            raw_text=raw_text,
            summary=summary
        )
        db.add(transcript)

       
        for t in extracted_tasks:
            priority_map = {
                "low": TaskPriority.low,
                "medium": TaskPriority.medium,
                "high": TaskPriority.high
            }
            task = Task(
                meeting_id=meeting.id,
                title=t.get("title", "Tâche sans titre"),
                description=t.get("description"),
                assignee=t.get("assignee"),
                priority=priority_map.get(t.get("priority", "medium"), TaskPriority.medium)
            )
            db.add(task)

      
        meeting.status = MeetingStatus.done
        db.commit()

        return {"status": "done", "meeting_id": meeting_id}

    except Exception as exc:
       
        meeting.status = MeetingStatus.failed
        db.commit()
        raise self.retry(exc=exc, countdown=10)

    finally:
        db.close()