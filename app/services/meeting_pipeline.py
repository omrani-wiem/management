"""Logique de sauvegarde commune au worker (upload) et au WebSocket (live)."""
from sqlalchemy.orm import Session

from app.config import settings
from app.models.decision import Decision
from app.models.meeting import Meeting, MeetingStatus
from app.models.segment import TranscriptSegment
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.team import Team, TeamMember
from app.models.transcript import Transcript

CONFIDENCE_THRESHOLD = 0.75
SUPPORTED_OUTPUT_LANGUAGES = {"fr", "en", "ar"}


# ---------------------------------------------------------------- noms

def merge_names(*groups: list[str]) -> list[str]:
    """Fusionne des listes de noms sans doublon (insensible à la casse), en gardant l'ordre."""
    seen: dict[str, str] = {}
    for group in groups:
        for name in group or []:
            n = (name or "").strip()
            if n and n.lower() not in seen:
                seen[n.lower()] = n
    return list(seen.values())


def get_known_names(db: Session, meeting: Meeting) -> list[str]:
    """Noms de référence pour Whisper et le LLM : participants saisis + membres des équipes
    DE CET UTILISATEUR (et non plus tous les utilisateurs de la base)."""
    query = (
        db.query(TeamMember.full_name)
        .join(Team, TeamMember.team_id == Team.id)
        .filter(Team.owner_id == meeting.owner_id)
    )
    if meeting.team_id:
        query = query.filter(Team.id == meeting.team_id)
    team_names = [n for (n,) in query.all()]
    owner_name = [meeting.owner.full_name] if meeting.owner and meeting.owner.full_name else []
    return merge_names(meeting.participants_list, team_names, owner_name)


# ---------------------------------------------------------------- langues

def resolve_spoken_language(meeting: Meeting) -> str | None:
    """Langue à passer à Whisper. None = détection automatique."""
    value = (meeting.language or settings.whisper_language or "auto").strip().lower()
    return None if value in {"", "auto"} else value


def resolve_output_language(meeting: Meeting, detected: str | None = None) -> str:
    """Langue du résumé / décisions / tâches : choix explicite, sinon langue parlée, sinon français."""
    for candidate in (meeting.output_language, meeting.language, detected):
        if candidate and candidate.strip().lower() in SUPPORTED_OUTPUT_LANGUAGES:
            return candidate.strip().lower()
    return "fr"


# ---------------------------------------------------------------- segments / horodatage

def format_timestamp(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def timestamped_text(segments: list[dict]) -> str:
    """Transcription avec marqueurs [mm:ss], envoyée au LLM pour qu'il horodate décisions et tâches."""
    return "\n".join(
        f"[{format_timestamp(s['start'])}] {s['text']}" for s in segments if s.get("text")
    )


def load_segments(db: Session, meeting: Meeting) -> list[dict]:
    rows = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.meeting_id == meeting.id)
        .order_by(TranscriptSegment.idx)
        .all()
    )
    return [{"start": r.start_seconds, "end": r.end_seconds, "text": r.text} for r in rows]


def save_segments(db: Session, meeting: Meeting, segments: list[dict]) -> None:
    db.query(TranscriptSegment).filter(TranscriptSegment.meeting_id == meeting.id).delete()
    for i, s in enumerate(segments):
        if not s.get("text"):
            continue
        db.add(
            TranscriptSegment(
                meeting_id=meeting.id,
                idx=i,
                start_seconds=float(s["start"]),
                end_seconds=float(s["end"]),
                text=s["text"],
            )
        )
    db.commit()


def transcript_for_llm(db: Session, meeting: Meeting, raw_text: str) -> str:
    segments = load_segments(db, meeting)
    return timestamped_text(segments) if segments else raw_text


# ---------------------------------------------------------------- sauvegardes

def save_transcript(
    db: Session,
    meeting: Meeting,
    raw_text: str,
    duration_seconds: int | None,
    language: str | None = None,
) -> Transcript:
    """Sauvegarde (ou met à jour) la transcription brute dès qu'elle existe."""
    transcript = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).first()
    if transcript is None:
        transcript = Transcript(meeting_id=meeting.id, raw_text=raw_text)
        db.add(transcript)
    else:
        transcript.raw_text = raw_text
    if duration_seconds is not None:
        meeting.duration_seconds = duration_seconds
    if language and not meeting.language:
        meeting.language = language[:10]   # langue détectée
    db.commit()
    return transcript


def save_analysis(
    db: Session,
    meeting: Meeting,
    analysis: dict,
    typed_participants: list[str] | None = None,
) -> dict:
    """Enregistre résumé, décisions, tâches et participants, puis passe la réunion à 'done'.
    Retourne {"tasks": [...], "decisions": [...]} (sérialisable en JSON, pour le live)."""
    transcript = db.query(Transcript).filter(Transcript.meeting_id == meeting.id).first()
    if transcript is None:
        raise ValueError("Transcription absente : impossible d'enregistrer l'analyse")
    transcript.summary = analysis["summary"]

    # Idempotent en cas de nouvelle exécution : on repart de zéro, sans doublons
    db.query(Task).filter(Task.meeting_id == meeting.id).delete()
    db.query(Decision).filter(Decision.meeting_id == meeting.id).delete()

    tasks_out: list[dict] = []
    for t in analysis["tasks"]:
        # En dessous du seuil de confiance, on ne désigne personne
        assignee = t["assignee"] if t["confidence"] >= CONFIDENCE_THRESHOLD else None
        db.add(
            Task(
                meeting_id=meeting.id,
                title=t["title"][:255],
                description=t["description"],
                assignee=assignee,
                priority=TaskPriority(t["priority"]),
                status=TaskStatus.todo,
                due_date=t.get("due_date"),
                source_seconds=t.get("timestamp"),
            )
        )
        tasks_out.append(
            {
                "title": t["title"],
                "description": t["description"],
                "assignee": assignee,
                "priority": t["priority"],
                "confidence": t["confidence"],
                "due_date": t["due_date"].isoformat() if t.get("due_date") else None,
                "timestamp": t.get("timestamp"),
            }
        )

    decisions_out: list[dict] = []
    for d in analysis["decisions"]:
        db.add(
            Decision(
                meeting_id=meeting.id,
                text=d["text"],
                rationale=d.get("rationale"),
                source_seconds=d.get("timestamp"),
            )
        )
        decisions_out.append(
            {"text": d["text"], "rationale": d.get("rationale"), "timestamp": d.get("timestamp")}
        )

    # Participants saisis par l'utilisateur d'abord, puis ceux détectés (plus d'écrasement)
    all_participants = merge_names(
        typed_participants or meeting.participants_list,
        analysis["participants_detected"],
    )
    meeting.participants = ", ".join(all_participants)[:1000] or None
    meeting.status = MeetingStatus.done
    db.commit()
    return {"tasks": tasks_out, "decisions": decisions_out}
