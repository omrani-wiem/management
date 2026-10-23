import logging
import os

from app.services.whisper_model import get_model, whisper_lock

logger = logging.getLogger(__name__)


def transcribe_audio(
    audio_path: str,
    known_names: list[str] | None = None,
    language: str | None = None,
) -> dict:
    """Transcrit un fichier audio. language=None -> détection automatique (fr / en / ar...).
    Retourne {"text", "language", "duration_seconds", "segments": [{start, end, text}]}."""
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Fichier audio introuvable : {audio_path}")

    # liste de noms propres : aide Whisper à bien les orthographier
    initial_prompt = ", ".join(known_names) if known_names else None

    model = get_model()
    with whisper_lock:
        # le générateur doit être consommé DANS le verrou : le décodage est paresseux
        segments_iter, info = model.transcribe(
            audio_path,
            language=language,
            initial_prompt=initial_prompt,
            vad_filter=True,
            beam_size=5,
        )
        segments = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments_iter
        ]

    text = " ".join(s["text"] for s in segments if s["text"]).strip()
    duration = round(segments[-1]["end"]) if segments else 0
    logger.info("Transcription terminée : %d segments, %ss, langue=%s", len(segments), duration, info.language)
    return {
        "text": text,
        "language": info.language,
        "duration_seconds": duration,
        "segments": segments,
    }
