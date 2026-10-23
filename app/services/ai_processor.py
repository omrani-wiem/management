import json
import logging
from datetime import date

from pydantic import ValidationError

from app.config import settings
from app.schemas.meeting import DecisionAnalyzed, MeetingAnalysis, TaskAnalyzed
from app.services.llm_provider import get_llm

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # tentatives si le JSON renvoyé est invalide
LANGUAGE_NAMES = {"fr": "French", "en": "English", "ar": "Arabic"}

SYSTEM_PROMPT = (
    "You are an expert assistant that analyses professional meeting transcripts. "
    "You reply ONLY with one valid JSON object, with no text before or after it. "
    "Write every free-text value (summary, decisions, tasks, descriptions) in {language}. "
    "Keep the JSON keys exactly as specified, in English."
)

JSON_FORMAT = """{
  "summary": "clear, structured summary of the meeting (5 to 10 sentences)",
  "participants_detected": ["First Last", "..."],
  "decisions": [
    {"text": "what was decided", "rationale": "why, or null", "timestamp": "mm:ss or null"}
  ],
  "tasks": [
    {
      "title": "short, concrete action",
      "description": "useful detail or null",
      "assignee": "First Last, or null if nobody is clearly designated",
      "confidence": 0.0,
      "priority": "low | medium | high",
      "due_date": "YYYY-MM-DD or null",
      "timestamp": "mm:ss or null"
    }
  ]
}"""


def _chunk_chars() -> int:
    # les modèles locaux ont un contexte plus court
    return 6000 if settings.llm_provider.strip().lower() == "ollama" else 12000


def _build_user_prompt(transcript: str, known_names: list[str], meeting_date: date | None) -> str:
    hints = ""
    if known_names:
        hints += ("Known names (reference spelling, use it to correct transcription errors): "
                  + ", ".join(known_names) + ".\n")
    if meeting_date:
        hints += f"Meeting date: {meeting_date.isoformat()} (use it to resolve relative dates such as 'next Friday').\n"
    return (
        "Analyse this meeting transcript.\n"
        + hints
        + "Rules:\n"
        "- Do not invent anything: only what is actually said in the transcript.\n"
        "- A DECISION is something the group explicitly agreed, approved, chose or rejected. "
        "A TASK is an action someone must do. Do not list the same thing twice.\n"
        "- 'confidence' (0 to 1) = how sure you are that the named person is responsible for the task. "
        "If responsibility is ambiguous, set assignee to null.\n"
        "- 'due_date' only if a date is stated or can be resolved from the meeting date, otherwise null.\n"
        "- Transcript lines may start with a [mm:ss] marker. For each decision and task, set 'timestamp' "
        "to the marker of the line where it was said, otherwise null.\n\n"
        f"Reply with exactly this JSON format:\n{JSON_FORMAT}\n\n"
        f"TRANSCRIPT:\n{transcript}"
    )


def _llm(messages: list[dict], json_mode: bool, max_tokens: int = 2000) -> str:
    return get_llm().chat(messages, json_mode=json_mode, max_tokens=max_tokens)


def _parse(raw: str) -> MeetingAnalysis:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("Aucun objet JSON dans la réponse")
    return MeetingAnalysis.model_validate(json.loads(raw[start:end + 1]))


def _analyze_chunk(transcript: str, known_names: list[str], language: str,
                   meeting_date: date | None) -> MeetingAnalysis:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(language=language)},
        {"role": "user", "content": _build_user_prompt(transcript, known_names, meeting_date)},
    ]
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = _llm(messages, json_mode=True)
        try:
            return _parse(raw)
        except (ValueError, ValidationError) as exc:  # JSONDecodeError et ValidationError héritent de ValueError
            last_error = exc
            logger.warning("Réponse LLM invalide (tentative %d/%d) : %s", attempt, MAX_ATTEMPTS, exc)
    raise ValueError(f"Le LLM n'a pas renvoyé un JSON valide après {MAX_ATTEMPTS} tentatives : {last_error}")


def _split_text(text: str, max_chars: int) -> list[str]:
    """Découpe en morceaux, en coupant de préférence entre deux lignes (segments horodatés)."""
    chunks, current, size = [], [], 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # une ligne énorme (sans retour à la ligne) est coupée par mots
        pieces = [line] if len(line) <= max_chars else _split_words(line, max_chars)
        for piece in pieces:
            if size + len(piece) + 1 > max_chars and current:
                chunks.append("\n".join(current))
                current, size = [], 0
            current.append(piece)
            size += len(piece) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _split_words(text: str, max_chars: int) -> list[str]:
    out, cur, size = [], [], 0
    for word in text.split():
        if size + len(word) + 1 > max_chars and cur:
            out.append(" ".join(cur))
            cur, size = [], 0
        cur.append(word)
        size += len(word) + 1
    if cur:
        out.append(" ".join(cur))
    return out


def _merge_summaries(summaries: list[str], language: str) -> str:
    joined = "\n\n".join(f"Part {i + 1}: {s}" for i, s in enumerate(summaries))
    return _llm(
        [
            {"role": "system",
             "content": f"You write faithful, clear meeting minutes. Write in {language}."},
            {"role": "user",
             "content": "Here are the successive summaries of the parts of ONE meeting. Merge them into a single "
                        "coherent summary of 5 to 10 sentences, without inventing anything.\n\n" + joined},
        ],
        json_mode=False,
        max_tokens=800,
    ).strip()


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def analyze_meeting(
    transcript: str,
    known_names: list[str] | None = None,
    output_language: str = "fr",
    meeting_date: date | None = None,
) -> dict:
    """Analyse une transcription et retourne un dict validé :
    {"summary", "participants_detected", "decisions": [...], "tasks": [...]}

    Lève ValueError / une erreur du fournisseur si l'analyse échoue (l'appelant décide : retry ou échec)."""
    known_names = known_names or []
    language = LANGUAGE_NAMES.get(output_language, "French")
    chunks = _split_text(transcript, _chunk_chars())
    if not chunks:
        raise ValueError("Transcription vide")

    parts = [_analyze_chunk(c, known_names, language, meeting_date) for c in chunks]

    if len(parts) == 1:
        merged = parts[0]
    else:
        tasks: list[TaskAnalyzed] = []
        decisions: list[DecisionAnalyzed] = []
        seen_t: set[str] = set()
        seen_d: set[str] = set()
        for p in parts:
            for t in p.tasks:
                if _norm(t.title) not in seen_t:
                    seen_t.add(_norm(t.title))
                    tasks.append(t)
            for d in p.decisions:
                if _norm(d.text) not in seen_d:
                    seen_d.add(_norm(d.text))
                    decisions.append(d)
        participants = list({n.lower(): n for p in parts for n in p.participants_detected}.values())
        merged = MeetingAnalysis(
            summary=_merge_summaries([p.summary for p in parts], language),
            participants_detected=participants,
            decisions=decisions,
            tasks=tasks,
        )
    return merged.model_dump()
