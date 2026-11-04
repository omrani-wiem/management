import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (enregistre les modèles)
from app.config import settings
from app.database import Base, engine, get_db
from app.routers import auth, live, meetings, rag, tasks, team

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

if settings.auto_create_tables:
    logger.warning("AUTO_CREATE_TABLES actif : à réserver au développement (utilise Alembic en production)")
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)

if len(settings.secret_key) < 32:
    logger.warning("SECRET_KEY trop courte (< 32 caractères) : génère-en une longue et aléatoire")

app = FastAPI(
    title="Meeting AI API",
    version="1.0.0",
    description=(
        "Transcription de réunions (Whisper), résumé, décisions et tâches extraits par LLM "
        "(Groq ou Ollama), multilingue FR / EN / AR."
    ),
    openapi_tags=[
        {"name": "auth", "description": "Inscription et connexion (JWT)"},
        {"name": "meetings", "description": "Réunions : upload audio, détail, transcription horodatée"},
        {"name": "tasks", "description": "Tâches extraites des réunions"},
        {"name": "jira", "description": "Création et actualisation manuelle des tickets Jira"},
        {"name": "team", "description": "Équipes et membres"},
        {"name": "live", "description": "Transcription en direct (WebSocket)"},
        {"name": "rag", "description": "Questions sur les réunions passées, avec citations"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(meetings.router)
app.include_router(tasks.router)
app.include_router(live.router)
app.include_router(team.router)
app.include_router(rag.router)


@app.get("/health", tags=["health"])
def health():
    """Liveness : le processus répond."""
    return {"status": "ok", "message": "Meeting AI is running"}


@app.get("/health/ready", tags=["health"])
def ready(db: Session = Depends(get_db)):
    """Readiness : la base de données répond. Redis est signalé mais ne bloque pas."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Base de données indisponible")
        raise HTTPException(status_code=503, detail="Base de données indisponible")
    redis_status = "ok"
    try:
        import redis

        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
    except Exception:
        redis_status = "down"
    return {"status": "ready", "database": "ok", "redis": redis_status}
