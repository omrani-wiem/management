import asyncio
import json
import logging
import uuid
from collections import Counter

from fastapi import APIRouter, WebSocket

from app.auth_utils import get_user_from_token
from app.database import SessionLocal
from app.models.meeting import Meeting, MeetingStatus
from app.services.ai_processor import analyze_meeting
from app.services.live_transcription import transcribe_chunk
from app.workers.tasks import process_meeting
from app.services.meeting_pipeline import (
    get_known_names,
    resolve_output_language,
    resolve_spoken_language,
    save_analysis,
    save_segments,
    save_transcript,
    timestamped_text,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/live", tags=["live"])

AUTH_TIMEOUT_S = 10
MIN_CHUNK_BYTES = 100


async def _send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception:  # client déjà parti
        pass


async def _close(ws: WebSocket, code: int = 1000) -> None:
    try:
        await ws.close(code=code)
    except Exception:
        pass


@router.websocket("/meeting/{meeting_id}")
async def live_meeting(websocket: WebSocket, meeting_id: str):
    """Protocole :
      1. client -> {"type": "auth", "token": "<JWT>", "format": "file" | "pcm16"}
      2. client -> messages binaires (audio) ; serveur -> {"type": "transcript", ...}
      3. client -> {"type": "stop"}  ;  serveur -> {"type": "done", "summary", "decisions", "tasks", ...}
    """
    await websocket.accept()
    db = SessionLocal()
    meeting = None
    parts: list[str] = []
    all_segments: list[dict] = []
    detected_langs: list[str] = []
    elapsed = 0.0  # durée audio cumulée (sert à horodater les segments)
    handed_off = False  # True si l'analyse a été confiée au worker Celery

    try:
        # ---------- 1. Authentification (premier message) ----------
        try:
            first = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_S)
        except (asyncio.TimeoutError, ValueError, KeyError):
            await _send(websocket, {"type": "error", "message": "Authentification requise"})
            await _close(websocket, 4401)
            return

        user = None
        if isinstance(first, dict) and first.get("type") == "auth":
            user = get_user_from_token(str(first.get("token", "")), db)
        if user is None:
            await _send(websocket, {"type": "error", "message": "Token invalide"})
            await _close(websocket, 4401)
            return
        audio_format = first.get("format", "file")
        if audio_format not in {"file", "pcm16"}:
            audio_format = "file"

        # ---------- 2. La réunion doit appartenir à l'utilisateur ----------
        try:
            mid = uuid.UUID(meeting_id)
        except ValueError:
            await _send(websocket, {"type": "error", "message": "Identifiant de réunion invalide"})
            await _close(websocket, 4404)
            return
        meeting = db.query(Meeting).filter(Meeting.id == mid, Meeting.owner_id == user.id).first()
        if meeting is None:
            await _send(websocket, {"type": "error", "message": "Réunion introuvable"})
            await _close(websocket, 4404)
            return
        if meeting.status != MeetingStatus.pending:
            await _send(websocket, {"type": "error", "message": "Cette réunion a déjà été traitée"})
            await _close(websocket, 4409)
            return

        spoken_language = resolve_spoken_language(meeting)  # None = détection automatique
        meeting.status = MeetingStatus.processing
        db.commit()
        await _send(websocket, {"type": "status", "message": "Connecté, enregistrement en cours"})

        # ---------- 3. Réception de l'audio ----------
        disconnected = False
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                disconnected = True
                break

            if msg.get("text") is not None:
                try:
                    payload = json.loads(msg["text"])
                except ValueError:
                    continue
                if isinstance(payload, dict) and payload.get("type") == "stop":
                    break

            elif msg.get("bytes") is not None:
                chunk = msg["bytes"]
                if len(chunk) < MIN_CHUNK_BYTES:
                    continue
                # to_thread : la transcription ne bloque plus la boucle d'événements
                result = await asyncio.to_thread(transcribe_chunk, chunk, audio_format, spoken_language)
                for s in result["segments"]:
                    all_segments.append(
                        {"start": s["start"] + elapsed, "end": s["end"] + elapsed, "text": s["text"]}
                    )
                elapsed += result["duration"]
                if result["text"]:
                    parts.append(result["text"])
                    if result["language"]:
                        detected_langs.append(result["language"])
                    await _send(
                        websocket,
                        {"type": "transcript", "text": result["text"], "full": " ".join(parts)},
                    )

        # ---------- 4. Finalisation (aussi si le client s'est déconnecté) ----------
        notify = not disconnected
        full_text = " ".join(parts).strip()

        if not full_text:
            meeting.status = MeetingStatus.failed
            db.commit()
            if notify:
                await _send(websocket, {"type": "error", "message": "Aucune parole détectée"})
            return

        language = Counter(detected_langs).most_common(1)[0][0] if detected_langs else None
        save_transcript(db, meeting, full_text, round(elapsed) or None, language=language)
        save_segments(db, meeting, all_segments)  # le transcript n'est plus jamais perdu

        if disconnected:
            # Le client est parti : l'analyse est confiée au worker Celery (il reprend la transcription
            # sauvegardée). Elle survit ainsi à un redémarrage ou à un arrêt du serveur web.
            try:
                process_meeting.delay(str(meeting.id), meeting.participants_list)
                handed_off = True
            except Exception:
                logger.exception("Impossible de confier la réunion live %s au worker", meeting_id)
                meeting.status = MeetingStatus.failed
                db.commit()
            return

        if notify:
            await _send(websocket, {"type": "status", "message": "Génération du résumé, des décisions et des tâches..."})

        known_names = get_known_names(db, meeting)
        llm_text = timestamped_text(all_segments) or full_text
        output_language = resolve_output_language(meeting, language)
        meeting_date = meeting.created_at.date() if meeting.created_at else None
        try:
            analysis = await asyncio.to_thread(
                analyze_meeting, llm_text, known_names, output_language, meeting_date
            )
        except Exception:
            logger.exception("Analyse LLM échouée pour la réunion live %s", meeting_id)
            meeting.status = MeetingStatus.failed
            db.commit()
            if notify:
                await _send(
                    websocket,
                    {"type": "error", "message": "Transcription enregistrée, mais l'analyse a échoué"},
                )
            return

        saved = save_analysis(db, meeting, analysis, typed_participants=meeting.participants_list)
        if notify:
            await _send(
                websocket,
                {
                    "type": "done",
                    "summary": analysis["summary"],
                    "participants": meeting.participants_list,
                    "decisions": saved["decisions"],
                    "tasks": saved["tasks"],
                    "transcript": full_text,
                    "language": meeting.language,
                    "output_language": output_language,
                },
            )
            await _close(websocket, 1000)

    except asyncio.CancelledError:
        db.rollback()
        if meeting is not None and not handed_off:
            try:
                if meeting.status != MeetingStatus.done:
                    meeting.status = MeetingStatus.failed
                    db.commit()
            except Exception:
                db.rollback()
        raise
    except Exception:
        logger.exception("Erreur WebSocket live (réunion %s)", meeting_id)
        db.rollback()
        if meeting is not None:
            try:
                if meeting.status != MeetingStatus.done:
                    meeting.status = MeetingStatus.failed
                    db.commit()
            except Exception:
                db.rollback()
        await _send(websocket, {"type": "error", "message": "Erreur interne du serveur"})
        await _close(websocket, 1011)
    finally:
        db.close()
