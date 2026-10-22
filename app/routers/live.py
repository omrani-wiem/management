from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.meeting import Meeting, MeetingStatus
from app.models.transcript import Transcript
from app.models.task import Task, TaskPriority
from app.services.live_transcription import transcribe_chunk
from app.services.ai_processor import analyze_meeting
import json

router = APIRouter(prefix="/api/live", tags=["live"])

@router.websocket("/meeting/{meeting_id}")
async def live_meeting(websocket: WebSocket, meeting_id: str):
    await websocket.accept()
    db: Session = SessionLocal()
    full_transcript = []

    try:
        # Met la réunion en mode processing
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Réunion introuvable"
            }))
            return

        meeting.status = MeetingStatus.processing
        db.commit()

        await websocket.send_text(json.dumps({
            "type": "status",
            "message": "Connexion établie — enregistrement en cours"
        }))

        # Boucle principale — reçoit les chunks audio
        while True:
            data = await websocket.receive()

            # L'utilisateur envoie "stop" pour terminer
            if "text" in data:
                message = json.loads(data["text"])
                if message.get("type") == "stop":
                    break

            # Reçoit un chunk audio binaire
            elif "bytes" in data:
                audio_chunk = data["bytes"]

                if len(audio_chunk) < 100:
                    continue

                # Transcrit le chunk
                text = transcribe_chunk(audio_chunk)

                if text:
                    full_transcript.append(text)

                    # Envoie la transcription partielle au frontend
                    await websocket.send_text(json.dumps({
                        "type": "transcript",
                        "text": text,
                        "full": " ".join(full_transcript)
                    }))

        # Fin de l'enregistrement — génère résumé + tâches
        if full_transcript:
            complete_text = " ".join(full_transcript)

            await websocket.send_text(json.dumps({
                "type": "status",
                "message": "Génération du résumé en cours..."
            }))

            # Résumé
            analysis = analyze_meeting(complete_text)
            summary = analysis.get("summary", "")



            await websocket.send_text(json.dumps({
                "type": "status",
                "message": "Extraction des tâches en cours..."
            }))

            # Extraction tâches
            extracted_tasks = analysis.get("tasks", [])

            # Sauvegarde en base
            transcript = Transcript(
                meeting_id=meeting.id,
                raw_text=complete_text,
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
                    priority=priority_map.get(
                        t.get("priority", "medium"),
                        TaskPriority.medium
                    )
                )
                db.add(task)

            meeting.status = MeetingStatus.done
            db.commit()

            # Envoie les résultats finaux
            await websocket.send_text(json.dumps({
                "type": "done",
                "summary": summary,
                "tasks": extracted_tasks,
                "participants": analysis.get("participants_detected", []),
                "full_transcript": complete_text
            }))

        else:
            meeting.status = MeetingStatus.failed
            db.commit()
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Aucun audio capté"
            }))

    except WebSocketDisconnect:
        print(f"Client déconnecté : {meeting_id}")
        if full_transcript:
            meeting.status = MeetingStatus.done
        else:
            meeting.status = MeetingStatus.failed
        db.commit()

    finally:
        db.close()