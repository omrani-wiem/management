"""Vérifie que chaque fichier de la Phase 1 est au bon endroit et contient le bon code.
Usage (à la racine du projet, là où se trouve le dossier app/) :  python check_files.py
"""
import os
import re
import sys

# chemin : (texte obligatoire, texte interdit)
RULES = {
    "app/config.py": ("llm_provider", ""),
    "app/main.py": ("cors_origins_list", ""),
    "app/auth_utils.py": ("def get_user_from_token", "APIRouter"),
    "app/models/__init__.py": ("TranscriptSegment", "pydantic"),
    "app/models/task.py": ("source_seconds", "pydantic"),
    "app/models/meeting.py": ("output_language", "pydantic"),
    "app/models/decision.py": ("class Decision(Base)", "pydantic"),
    "app/models/segment.py": ("class TranscriptSegment(Base)", "pydantic"),
    "app/schemas/meeting.py": ("class DecisionAnalyzed", "__tablename__"),
    "app/schemas/task.py": ("source_seconds", "__tablename__"),
    "app/schemas/team.py": ("TeamMemberWithCount", "__tablename__"),
    "app/schemas/user.py": ("class UserCreate", "__tablename__"),
    "app/routers/auth.py": ("_check_rate_limit", "def get_user_from_token"),
    "app/routers/meetings.py": ("get_segments", "def get_user_from_token"),
    "app/routers/tasks.py": ("overdue", "celery_app"),
    "app/routers/team.py": ("list_members_with_workload", "celery_app"),
    "app/routers/live.py": ("all_segments", "celery_app"),
    "app/workers/tasks.py": ("save_segments", "APIRouter"),
    "app/services/llm_provider.py": ("def get_llm", ""),
    "app/services/ai_processor.py": ("get_llm", "from groq import"),
    "app/services/meeting_pipeline.py": ("def save_segments", ""),
    "app/services/whisper_model.py": ("whisper_lock", ""),
    "app/services/transcription.py": ("language: str | None = None", "import whisper\n"),
    "app/services/live_transcription.py": ('"duration"', ""),
}


def read(path):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


errors = 0
if not os.path.isdir("app"):
    sys.exit("ERREUR : lance ce script depuis la racine du projet (là où se trouve le dossier app/).")

for path, (must, forbidden) in RULES.items():
    if not os.path.exists(path):
        print(f"MANQUANT   {path}")
        errors += 1
        continue
    text = read(path)
    problems = []
    if must and must not in text:
        problems.append(f"ne contient pas « {must} » (ancienne version ou mauvais fichier)")
    if forbidden and forbidden in text:
        problems.append(f"contient « {forbidden.strip()} » qui n'a rien à faire ici (fichier mélangé)")
    module = path[:-3].replace("/", ".")
    if re.search(rf"^\s*from\s+{re.escape(module)}\s+import", text, re.M):
        problems.append("s'importe lui-même (import circulaire)")
    if problems:
        errors += 1
        print(f"ERREUR     {path}")
        for p in problems:
            print(f"             - {p}")
    else:
        print(f"ok         {path}")

# fichiers .py inconnus dans services/ (anciens moteurs à supprimer ?)
known = {os.path.basename(p) for p in RULES if p.startswith("app/services/")} | {"__init__.py"}
for name in sorted(os.listdir("app/services")):
    if name.endswith(".py") and name not in known:
        print(f"A VERIFIER app/services/{name} (ancien fichier ? peut-être à supprimer)")

print()
print("TOUT EST BON : tu peux lancer uvicorn." if errors == 0 else f"{errors} fichier(s) à corriger : recopie-les depuis le zip.")
sys.exit(1 if errors else 0)
