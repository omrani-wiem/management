"""Vérifie que chaque fichier de la Phase 1 est au bon endroit et contient le bon code.
Usage (à la racine du projet, là où se trouve le dossier app/) :  python check_files.py
"""
import os
import re
import sys

# chemin : (texte obligatoire, texte interdit)
RULES = {
    "RAG_NOTES.md": ("pgvector", ""),
    "rag_eval/__main__.py": ("--no-llm", ""),
    "rag_eval/metrics.py": ("def is_relevant", ""),
    "rag_eval/runner.py": ("def evaluate", ""),
    "tests/fakes.py": ("HashingEmbedder", ""),
    "tests/test_rag_unit.py": ("test_hallucination_guard", ""),
    "tests/test_rag_pg.py": ("test_users_never_see_each_others_passages", ""),
    "alembic/versions/0003_rag_chunks.py": ("TSV_EXPRESSION", ""),
    "app/models/chunk.py": ("class MeetingChunk(Base)", "pydantic"),
    "app/services/embeddings.py": ("FastEmbedEmbedder", ""),
    "app/services/rag.py": ("def answer_question", ""),
    "app/schemas/rag.py": ("class AskRequest", "__tablename__"),
    "app/routers/rag.py": ("/ask", "def get_user_from_token"),
    "requirements.txt": ("fastembed", ""),
    "requirements-dev.txt": ("pytest", ""),
    "pyproject.toml": ("[tool.pytest.ini_options]", ""),
    "alembic.ini": ("script_location", ""),
    "alembic/env.py": ("target_metadata = Base.metadata", ""),
    "alembic/versions/0001_baseline.py": ("def upgrade", ""),
    "alembic/versions/0002_tasks_meeting_index.py": ("ix_tasks_meeting_id", ""),
    "Dockerfile": ("uvicorn", ""),
    "docker-compose.yml": ("5433:5432", ""),
    ".github/workflows/ci.yml": ("alembic check", ""),
    "README.md": ("RAG : interroger ses réunions", ""),
    "tests/conftest.py": ("TEST_DATABASE_URL", ""),
    "tests/test_auth.py": ("test_every_route_requires_authentication", ""),
    "tests/test_live.py": ("test_disconnect_hands_analysis_to_worker", ""),
    "tests/test_pipeline.py": ("test_failed_analysis_keeps_transcript", ""),
    "app/config.py": ("auto_create_tables", ""),
    "app/main.py": ("rag.router", ""),
    "app/auth_utils.py": ("def get_user_from_token", "APIRouter"),
    "app/models/__init__.py": ("MeetingChunk", "pydantic"),
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
    "app/routers/live.py": ("index_meeting_task", "celery_app ="),
    "app/workers/tasks.py": ("index_meeting_task", "APIRouter"),
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
    if path.endswith(".py") and re.search(rf"^\s*from\s+{re.escape(module)}\s+import", text, re.M):
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

if os.path.exists("smoke_test.py"):
    print("A SUPPRIMER smoke_test.py (remplacé par pytest : lance simplement `pytest`)")
print()
print("TOUT EST BON : tu peux lancer uvicorn." if errors == 0 else f"{errors} fichier(s) à corriger : recopie-les depuis le zip.")
sys.exit(1 if errors else 0)
