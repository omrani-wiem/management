import whisper
import os 
from app.config import settings

model = whisper.load_model(settings.whisper_model)

def transcribe_audio(audio_path: str, known_names: list[str] | None = None)  -> dict:
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Le fichier audio {audio_path} n'existe pas.")
    
    initial_prompt = None
    if known_names:
        names_str = ", ".join(known_names)


        initial_prompt = (f"Réunion d'équipe en francais "
                          f"Participants présents : {names_str}."
                          f"Les intervenants se nomment entre eux par leur prénom."
                          "Les participants se donnent des tâches en utilisant des expressions comme "
                          "'X doit...', 'Y va...', 'charge X de...', 'responsable: X'. "
                          )


    
    result = model.transcribe(
        audio_path,
        fp16=False,
        verbose=False,
        language="fr",
        initial_prompt=initial_prompt
        )
    

    segments = result.get("segments") or []
    duration_seconds = round(segments[-1]["end"]) if segments else 0

    return {
        "text": result["text"].strip(),
        "language": result["language"],
        "duration_seconds": duration_seconds
    }