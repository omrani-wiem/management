import io
import logging

import numpy as np

from app.services.whisper_model import get_model, whisper_lock

logger = logging.getLogger(__name__)

PCM_SAMPLE_RATE = 16000


def transcribe_chunk(audio_bytes: bytes, audio_format: str = "file", language: str | None = None) -> dict:
    """Transcrit un morceau audio reçu en live.

    audio_format :
      - "file"  : le morceau est un fichier audio AUTONOME (webm/ogg/wav... avec son en-tête).
      - "pcm16" : PCM 16 bits mono 16 kHz brut (le plus robuste côté serveur).

    Un chunk webm pris "au milieu" d'un MediaRecorder n'est PAS décodable seul : le client doit
    soit relancer le recorder à chaque segment, soit envoyer du pcm16.

    Retourne {"text", "segments" (temps relatifs au chunk), "duration" (secondes), "language"}."""
    empty = {"text": "", "segments": [], "duration": 0.0, "language": None}
    try:
        if audio_format == "pcm16":
            usable = audio_bytes[: len(audio_bytes) // 2 * 2]
            audio = np.frombuffer(usable, dtype=np.int16).astype(np.float32) / 32768.0
            duration = len(audio) / PCM_SAMPLE_RATE
        else:
            audio = io.BytesIO(audio_bytes)
            duration = None

        model = get_model()
        with whisper_lock:
            segments_iter, info = model.transcribe(
                audio,
                language=language,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=False,
            )
            segments = [
                {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segments_iter
            ]
        text = " ".join(s["text"] for s in segments if s["text"]).strip()
        return {
            "text": text,
            "segments": segments,
            "duration": float(duration if duration is not None else (info.duration or 0.0)),
            "language": info.language if text else None,
        }
    except Exception:
        logger.exception("Erreur de transcription live")
        return empty
