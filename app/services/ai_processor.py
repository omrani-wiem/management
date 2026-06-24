from groq import Groq
from app.config import settings
import json

client = Groq(api_key=settings.groq_api_key)

def summarize_transcript(transcript: str) -> str:
    """
    Génère un résumé concis de la transcription.
    """
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "Tu es un assistant qui résume des réunions professionnelles en français. Sois concis et clair."
            },
            {
                "role": "user",
                "content": f"""Voici la transcription d'une réunion :

{transcript}

Génère un résumé en 5 phrases maximum qui capture les points essentiels discutés."""
            }
        ],
        temperature=0.3,
        max_tokens=500
    )
    return response.choices[0].message.content

def extract_tasks(transcript: str) -> list:
    """
    Extrait les user stories / tâches Scrum depuis la transcription.
    Retourne une liste JSON structurée.
    """
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Tu es un assistant Scrum Master expert. 
Tu analyses des transcriptions de réunions et extrais les tâches sous forme de user stories.
Tu réponds UNIQUEMENT en JSON valide, sans texte avant ou après."""
            },
            {
                "role": "user",
                "content": f"""Analyse cette transcription de réunion et extrais toutes les tâches mentionnées.

Transcription :
{transcript}

Réponds UNIQUEMENT avec ce JSON (sans texte autour) :
{{
  "tasks": [
    {{
      "title": "Titre court de la tâche",
      "description": "Description détaillée",
      "assignee": "Nom de la personne assignée ou null",
      "priority": "low|medium|high"
    }}
  ]
}}

Si aucune tâche n'est mentionnée, retourne {{"tasks": []}}"""
            }
        ],
        temperature=0.1,
        max_tokens=1000
    )

    raw = response.choices[0].message.content.strip()

    try:
        data = json.loads(raw)
        return data.get("tasks", [])
    except json.JSONDecodeError:
     
        return []