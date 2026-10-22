from groq import Groq
from app.config import settings
from app.schemas.meeting import MeetingAnalysis  # on va créer ce schema
import json

client = Groq(api_key=settings.groq_api_key)


def analyze_meeting(transcript: str, known_names: list[str] | None = None) -> dict:
    """
    Un seul appel LLM qui retourne :
    - résumé
    - participants détectés
    - tâches avec assignation + priorité + score de confiance
    """

    participants_hint = ""
    if known_names:
        names_str = ", ".join(known_names)
        participants_hint = f"""
Les participants connus de cette réunion sont : {names_str}.
- Pour "participants_detected", liste uniquement ceux dont tu entends la voix ou qui sont mentionnés.
- Pour "assignee", utilise UNIQUEMENT un nom de cette liste. Si incertain, mets null.
"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Tu es un assistant Scrum Master expert en analyse de réunions professionnelles.
Tu analyses des transcriptions et retournes une analyse structurée complète.
Tu réponds UNIQUEMENT en JSON valide, sans texte avant ou après, sans markdown."""
            },
            {
                "role": "user",
                "content": f"""Analyse cette transcription de réunion d'équipe.
{participants_hint}

Transcription :
{transcript}

Réponds UNIQUEMENT avec ce JSON (sans texte autour) :
{{
  "summary": "Résumé clair en 5 phrases maximum",
  "participants_detected": ["Nom 1", "Nom 2"],
  "tasks": [
    {{
      "title": "Titre court et actionnable",
      "description": "Ce qui doit être fait exactement",
      "assignee": "Nom complet ou null",
      "confidence": 0.95,
      "priority": "low|medium|high"
    }}
  ]
}}

Règles strictes :
- confidence = 1.0 si le nom est explicitement mentionné avec la tâche
- confidence = 0.7-0.9 si c'est fortement implicite
- confidence < 0.7 → mets assignee à null
- Si aucune tâche : "tasks": []
- Si aucun participant détecté : "participants_detected": []"""
            }
        ],
        temperature=0.1,
        max_tokens=1500
    )

    raw = response.choices[0].message.content.strip()

    # Nettoyer les éventuels backticks markdown
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback safe
        return {
            "summary": "Résumé indisponible.",
            "participants_detected": [],
            "tasks": []
        }