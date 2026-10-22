from faster_whisper import WhisperModel
import numpy as np
import io
import wave

# Charge le modèle une seule fois
model = WhisperModel("base", device="cpu", compute_type="int8")

def transcribe_chunk(audio_bytes: bytes) -> str:
    """
    Transcrit un chunk audio reçu via WebSocket.
    Retourne le texte transcrit.
    """
    try:
        # Convertit les bytes en fichier WAV en mémoire
        audio_buffer = io.BytesIO(audio_bytes)
        
        # Transcrit avec faster-whisper
        segments, _ = model.transcribe(
            audio_buffer,
            language="fr",
            vad_filter=True,        # filtre les silences
            vad_parameters=dict(
                min_silence_duration_ms=500
            )
        )
        
        # Combine tous les segments
        text = " ".join([seg.text for seg in segments]).strip()
        return text
        
    except Exception as e:
        print(f"Erreur transcription chunk : {e}")
        return ""