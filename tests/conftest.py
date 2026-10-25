"""Configuration des tests.

Par défaut : base SQLite temporaire (rapide, aucun service requis).
Pour tester sur PostgreSQL :  TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/meetingai_test
Whisper et le LLM sont toujours simulés. Ton .env et ta vraie base ne sont JAMAIS utilisés.
"""
import json
import os
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace

# --- l'environnement de test DOIT être posé avant tout import de l'application ---
_default_db = f"sqlite:///{tempfile.gettempdir()}/meeting_ai_pytest.db?check_same_thread=false"
_db_url = os.environ.get("TEST_DATABASE_URL", _default_db)
if not _db_url.startswith("sqlite") and not _db_url.split("?")[0].endswith("_test"):
    raise SystemExit(
        "TEST_DATABASE_URL doit pointer vers une base de TEST (nom finissant par _test) : "
        "les tests vident les tables."
    )
IS_PG = not _db_url.startswith("sqlite")
os.environ.update(
    RAG_ENABLED="true" if IS_PG else "false",   # le RAG a besoin de pgvector (PostgreSQL)
    DATABASE_URL=_db_url,
    SECRET_KEY="test-secret-key-" + "x" * 32,
    REDIS_URL="redis://localhost:6379/15",
    LLM_PROVIDER="groq",
    GROQ_API_KEY="test-key",
    WHISPER_LANGUAGE="auto",
    AUTO_CREATE_TABLES="false",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
import app.routers.auth as auth_router  # noqa: E402
import app.routers.live as live_router  # noqa: E402
import app.routers.meetings as meetings_router  # noqa: E402
import app.routers.rag as rag_router  # noqa: E402
import app.services.ai_processor as ai_processor  # noqa: E402
import app.services.rag as rag_service  # noqa: E402
from app.services import embeddings  # noqa: E402
import app.workers.tasks as worker  # noqa: E402
from app.database import Base, engine  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from tests.fakes import HashingEmbedder  # noqa: E402

WAV = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64
PASSWORD = "motdepasse1"


TABLES = [t for t in Base.metadata.sorted_tables if IS_PG or t.name != "meeting_chunks"]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    if IS_PG:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(engine, tables=TABLES)
    Base.metadata.create_all(engine, tables=TABLES)
    yield
    Base.metadata.drop_all(engine, tables=TABLES)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean():
    """Vide toutes les tables et la limitation de connexions entre deux tests."""
    with engine.begin() as conn:
        for table in reversed(TABLES):
            conn.execute(table.delete())
    auth_router._failed.clear()
    yield


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    """Aucun vrai modèle d'embedding n'est jamais chargé dans les tests."""
    embedder = HashingEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda: embedder)
    return embedder


@pytest.fixture
def client():
    with TestClient(fastapi_app) as c:
        yield c


def register(client, email="alice@test.com", name=None) -> dict:
    """Crée un compte, se connecte, retourne les en-têtes d'authentification."""
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": name or email.split("@")[0].title()},
    )
    assert r.status_code == 201, r.text
    token = client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice(client):
    return register(client, "alice@test.com")


@pytest.fixture
def bob(client):
    return register(client, "bob@test.com")


def default_segments():
    return [
        {"start": 0.0, "end": 5.0, "text": "Bonjour à tous."},
        {"start": 5.0, "end": 12.5, "text": "On décide de migrer vers PostgreSQL."},
        {"start": 12.5, "end": 20.0, "text": "Ali enverra le devis avant vendredi."},
    ]


def default_analysis():
    return {
        "summary": "Résumé test",
        "participants_detected": ["Ali Ben Salah"],
        "decisions": [{"text": "Migrer vers PostgreSQL", "rationale": "performance", "timestamp": "00:05"}],
        "tasks": [
            {"title": "Envoyer le devis", "assignee": "Ali Ben Salah", "confidence": 0.9, "priority": "high",
             "due_date": (date.today() - timedelta(days=3)).isoformat(), "timestamp": "00:12"},
            {"title": "Tâche floue", "assignee": "Sara", "confidence": 0.4, "priority": "urgent",
             "due_date": "demain", "timestamp": None},
        ],
    }


@pytest.fixture
def pipeline(monkeypatch):
    """Simule Whisper, le LLM et Celery (le vrai worker s'exécute, mais en local et sans Redis).

    Réglages possibles dans un test :  pipeline.analysis = {...}  /  pipeline.llm_error = RuntimeError(...)
    /  pipeline.segments = [...]  /  pipeline.worker_results (liste des retours du worker)."""
    state = SimpleNamespace(
        segments=default_segments(),
        analysis=default_analysis(),
        llm_error=None,
        detected_language="fr",
        transcribe_calls=0,
        whisper_language="<jamais appelé>",
        prompts=[],
        worker_results=[],
        delay_error=None,
        index_calls=[],
        rag_prompts=[],
        rag_reply={"answerable": True, "answer": "Réponse [1]", "citations": [1]},   # dict, str ou fonction(messages)
    )

    def fake_transcribe(path, known_names=None, language=None):
        state.transcribe_calls += 1
        state.whisper_language = language
        text = " ".join(s["text"] for s in state.segments)
        return {"text": text, "language": state.detected_language,
                "duration_seconds": round(state.segments[-1]["end"]) if state.segments else 0,
                "segments": state.segments}

    def fake_llm(messages, json_mode, max_tokens=2000):
        state.prompts.append(messages)
        if state.llm_error:
            raise state.llm_error
        return json.dumps(state.analysis)

    class Runner:  # remplace process_meeting.delay
        @staticmethod
        def delay(meeting_id, participants):
            if state.delay_error:
                raise state.delay_error
            result = worker.process_meeting.apply(args=[meeting_id, participants])
            state.worker_results.append(result)
            return result

    def fake_rag_llm(messages, json_mode=True, max_tokens=800):
        state.rag_prompts.append(messages)
        reply = state.rag_reply(messages) if callable(state.rag_reply) else state.rag_reply
        return reply if isinstance(reply, str) else json.dumps(reply)

    class IndexRunner:  # remplace index_meeting_task.delay
        @staticmethod
        def delay(meeting_id):
            state.index_calls.append(meeting_id)
            return worker.index_meeting_task.apply(args=[meeting_id])

    monkeypatch.setattr(rag_service, "_llm", fake_rag_llm)
    monkeypatch.setattr(live_router, "index_meeting_task", IndexRunner)
    monkeypatch.setattr(rag_router, "index_meeting_task", IndexRunner)
    monkeypatch.setattr(worker, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(ai_processor, "_llm", fake_llm)
    monkeypatch.setattr(meetings_router, "process_meeting", Runner)
    monkeypatch.setattr(live_router, "process_meeting", Runner)
    state.runner = Runner
    return state


@pytest.fixture
def upload(client):
    """upload(headers, title=..., **champs_form) -> réponse HTTP"""
    created = []

    def _upload(headers, title="Sprint", filename="reunion.wav", content=WAV, **form):
        r = client.post("/api/meetings/upload", headers=headers, data={"title": title, **form},
                        files={"file": (filename, content, "audio/wav")})
        if r.status_code == 200:
            created.append(r.json()["id"])
        return r

    yield _upload
    # nettoyage des fichiers audio créés par les tests
    from app.database import SessionLocal
    from app.models.meeting import Meeting

    with SessionLocal() as db:
        for mid in created:
            m = db.get(Meeting, __import__("uuid").UUID(mid))
            if m and m.audio_path and os.path.exists(m.audio_path):
                os.remove(m.audio_path)
