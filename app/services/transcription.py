import whisper
import os 
from app.config import settings

model = whisper.load_model(settings.whisper_model)

def transcribe_audio(audio_path: str) -> dict:
    """
    Transcrit un fichier audio en texte.
    Retourne le texte et la langue detectée.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Le fichier audio {audio_path} n'existe pas.")
    
    result = model.transcribe(audio_path, fp16=False, verbose=False)

    return {
        "text": result["text"].strip(),
        "language": result["language"]
    }