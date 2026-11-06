import logging
import re
import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models  # noqa: F401  (enregistre les modèles)
from app.config import settings
from app.auth_utils import get_user_from_token
from app.database import Base, SessionLocal, engine, get_db
from app.models.audit_event import AuditEvent
from app.routers import audit, auth, live, meetings, rag, tasks, team

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
        {"name": "audit", "description": "Historique des appels API authentifiés, limité à l'utilisateur courant"},
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
app.include_router(audit.router)
app.include_router(live.router)
app.include_router(team.router)
app.include_router(rag.router)


@app.middleware("http")
async def audit_authenticated_requests(request, call_next):
    """Journalise les métadonnées des appels API authentifiés, jamais leur contenu."""
    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return await call_next(request)

    db = SessionLocal()
    try:
        user = get_user_from_token(token, db)
        try:
            response = await call_next(request)
        except Exception:
            if user is not None:
                _record_audit_event(db, request, user.id, 500)
            raise

        if user is not None:
            response.headers["X-Request-ID"] = _record_audit_event(
                db, request, user.id, response.status_code
            )
        return response
    finally:
        db.close()


def _record_audit_event(db, request, actor_id, status_code: int) -> str:
    route = request.scope.get("route")
    endpoint = getattr(route, "path", None)
    if not endpoint:
        return str(uuid.uuid4())
    resource_id = next(
        (part for part in request.url.path.split("/") if re.fullmatch(r"[0-9a-fA-F-]{36}", part)),
        None,
    )
    request_id = str(uuid.uuid4())
    db.add(
        AuditEvent(
            actor_id=actor_id,
            method=request.method,
            endpoint=endpoint[:255],
            resource_id=resource_id,
            status_code=status_code,
            request_id=request_id,
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Impossible d'enregistrer l'événement d'audit")
        raise
    return request_id


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
