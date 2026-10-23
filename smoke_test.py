"""Test de bout en bout SANS Postgres / Redis / Whisper / Groq (tout est simulé, base SQLite temporaire).
Usage, à la racine du projet :   python smoke_test.py
Il ne touche ni à ta base PostgreSQL ni à ton .env, et supprime les fichiers qu'il crée.
"""
import glob
import os
import sys

sys.path.insert(0, os.getcwd())
_before = set(glob.glob(os.path.join("uploads", "*")))
for _f in ("smoke_test.db",):
    if os.path.exists(_f):
        os.remove(_f)
import json, types
os.environ.update(DATABASE_URL="sqlite:///./smoke_test.db?check_same_thread=false", SECRET_KEY="x"*32,
                  REDIS_URL="redis://localhost:6379/0", GROQ_API_KEY="dummy", LLM_PROVIDER="groq")
from fastapi.testclient import TestClient
from datetime import date, timedelta

ok = True
def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  -> {extra}" if (extra and not cond) else ""))

import app.main as main
from app.routers import meetings as meetings_router
import app.workers.tasks as wt
import app.services.ai_processor as ap
import app.routers.live as live

# --- faux Whisper + faux LLM ---
calls = {"prompts": []}
def fake_transcribe(path, known_names=None, language=None):
    calls["whisper_language"] = language
    segs = [{"start": 0.0, "end": 5.0, "text": "Bonjour à tous."},
            {"start": 5.0, "end": 12.5, "text": "On décide de migrer vers PostgreSQL."},
            {"start": 12.5, "end": 20.0, "text": "Ali enverra le devis avant vendredi."}]
    return {"text": " ".join(s["text"] for s in segs), "language": "fr", "duration_seconds": 20, "segments": segs}
wt.transcribe_audio = fake_transcribe

def fake_llm(messages, json_mode, max_tokens=2000):
    calls["prompts"].append(messages)
    past = (date.today() - timedelta(days=3)).isoformat()
    return json.dumps({"summary": "Résumé test", "participants_detected": ["Ali Ben Salah"],
        "decisions": [{"text": "Migrer vers PostgreSQL", "rationale": "performance", "timestamp": "00:05"}],
        "tasks": [{"title": "Envoyer le devis", "assignee": "Ali Ben Salah", "confidence": 0.9,
                   "priority": "high", "due_date": past, "timestamp": "00:12"},
                  {"title": "Tâche floue", "assignee": "Sara", "confidence": 0.4, "priority": "urgent",
                   "due_date": "demain", "timestamp": None}]})
ap._llm = fake_llm

class FakeTask:  # remplace .delay : exécute le vrai worker en local, sans Redis
    @staticmethod
    def delay(meeting_id, participants):
        calls["delay"] = (meeting_id, participants)
        r = wt.process_meeting.apply(args=[meeting_id, participants])
        calls["worker_result"] = r.result
meetings_router.process_meeting = FakeTask
live.process_meeting = FakeTask

with TestClient(main.app) as c:
    def reg(email):
        r = c.post("/api/auth/register", json={"email": email, "password": "motdepasse1", "full_name": email.split("@")[0].title()})
        assert r.status_code == 201, r.text
        t = c.post("/api/auth/login", json={"email": email, "password": "motdepasse1"}).json()["access_token"]
        return {"Authorization": f"Bearer {t}"}
    A, B = reg("alice@test.com"), reg("bob@test.com")
    check("login formulaire /token (Swagger)", c.post("/api/auth/token", data={"username": "alice@test.com", "password": "motdepasse1"}).status_code == 200)

    # équipe
    team = c.post("/api/team/", json={"name": "Dev"}, headers=A).json()
    c.post(f"/api/team/{team['id']}/members", json={"full_name": "Ali Ben Salah", "role": "Dev"}, headers=A)

    # upload avec participants + langue arabe + sortie anglaise
    wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 64
    r = c.post("/api/meetings/upload", headers=A, data={"title": "Sprint", "participants": "Ali, Sara", "language": "ar", "output_language": "en"},
               files={"file": ("réunion.wav", wav, "audio/wav")})
    check("upload 200", r.status_code == 200, r.text)
    mid = r.json()["id"]
    check("worker OK", calls.get("worker_result", {}).get("status") == "done", calls.get("worker_result"))
    check("Whisper reçoit language='ar'", calls.get("whisper_language") == "ar", calls.get("whisper_language"))
    sys_prompt = calls["prompts"][0][0]["content"]; user_prompt = calls["prompts"][0][1]["content"]
    check("prompt demande la sortie en English", "in English" in sys_prompt, sys_prompt)
    check("transcript envoyé au LLM avec marqueurs [mm:ss]", "[00:05] On décide" in user_prompt)
    check("date de réunion dans le prompt", date.today().isoformat() in user_prompt)

    d = c.get(f"/api/meetings/{mid}", headers=A).json()
    check("GET meeting : summary rempli (régression Phase 1)", d.get("summary") == "Résumé test", d)
    check("GET meeting : raw_text rempli", "PostgreSQL" in (d.get("raw_text") or ""))
    check("GET meeting : participants saisis conservés + détectés", d["participants"] and "Sara" in d["participants"] and "Ali Ben Salah" in d["participants"], d["participants"])
    check("GET meeting : décision + timestamp", d["decisions"] and d["decisions"][0]["source_seconds"] == 5, d["decisions"])
    check("langue : parlée=ar, sortie=en", d["language"] == "ar" and d["output_language"] == "en", (d["language"], d["output_language"]))
    check("durée enregistrée", d["duration_seconds"] == 20)

    segs = c.get(f"/api/meetings/{mid}/segments", headers=A).json()
    check("3 segments horodatés", len(segs) == 3 and segs[1]["start_seconds"] == 5.0, segs)

    tasks = c.get("/api/tasks/", headers=A).json()
    check("2 tâches", len(tasks) == 2, tasks)
    t1 = [t for t in tasks if t["title"] == "Envoyer le devis"][0]
    t2 = [t for t in tasks if t["title"] == "Tâche floue"][0]
    check("assignee gardé si confiance ≥ 0.75", t1["assignee"] == "Ali Ben Salah")
    check("assignee retiré si confiance < 0.75", t2["assignee"] is None)
    check("priorité invalide -> medium", t2["priority"] == "medium")
    check("date invalide ('demain') -> null", t2["due_date"] is None)
    check("source_seconds de la tâche", t1["source_seconds"] == 12)
    check("filtre overdue", [t["id"] for t in c.get("/api/tasks/?overdue=true", headers=A).json()] == [t1["id"]])
    check("filtre assignee", len(c.get("/api/tasks/?assignee=ali ben salah", headers=A).json()) == 1)
    check("filtre status", len(c.get("/api/tasks/?status=done", headers=A).json()) == 0)
    p = c.patch(f"/api/tasks/{t1['id']}", json={"status": "done", "due_date": None}, headers=A).json()
    check("PATCH status + effacer échéance", p["status"] == "done" and p["due_date"] is None, p)
    check("overdue ignore les tâches terminées", c.get("/api/tasks/?overdue=true", headers=A).json() == [])

    members = c.get("/api/team/members", headers=A).json()
    check("task_count d'Ali = 1", members and members[0]["task_count"] == 1, members)

    # isolation
    check("B ne voit pas la réunion de A", c.get(f"/api/meetings/{mid}", headers=B).status_code == 404)
    check("B ne voit pas les segments de A", c.get(f"/api/meetings/{mid}/segments", headers=B).status_code == 404)
    check("B : 0 tâche, 0 équipe", c.get("/api/tasks/", headers=B).json() == [] and c.get("/api/team/", headers=B).json() == [])
    check("B ne peut pas modifier la tâche de A", c.patch(f"/api/tasks/{t2['id']}", json={"status": "done"}, headers=B).status_code == 404)
    check("language invalide -> 400", c.post("/api/meetings/upload", headers=A, data={"title": "x", "language": "klingon"}, files={"file": ("a.wav", wav, "audio/wav")}).status_code == 400)
    check("faux audio -> 400", c.post("/api/meetings/upload", headers=A, data={"title": "x"}, files={"file": ("a.mp3", b"ceci est du texte brut....", "audio/mpeg")}).status_code == 400)

    # ---- live ----
    mid2 = c.post("/api/meetings/create", json={"title": "Live", "language": "auto"}, headers=A).json()["id"]
    n = {"i": 0}
    def fake_chunk(chunk, fmt, language):
        n["i"] += 1
        calls["live_language"] = language
        return {"text": f"phrase {n['i']}", "segments": [{"start": 0.0, "end": 4.0, "text": f"phrase {n['i']}"}], "duration": 8.0, "language": "en"}
    live.transcribe_chunk = fake_chunk
    token = A["Authorization"].split()[1]
    with c.websocket_connect(f"/api/live/meeting/{mid2}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token, "format": "file"}))
        ws.receive_json()  # status
        for _ in range(2):
            ws.send_bytes(b"\x01" * 500); ws.receive_json()
        ws.send_text(json.dumps({"type": "stop"}))
        msgs = []
        while True:
            m = ws.receive_json(); msgs.append(m)
            if m["type"] in ("done", "error"): break
    done = msgs[-1]
    check("live : message done avec décisions et tâches", done["type"] == "done" and done["decisions"] and done["tasks"], done)
    check("live : langue détectée 'en' et sortie 'en'", done["language"] == "en" and done["output_language"] == "en", (done.get("language"), done.get("output_language")))
    segs2 = c.get(f"/api/meetings/{mid2}/segments", headers=A).json()
    check("live : segments décalés (0 s puis 8 s)", [s["start_seconds"] for s in segs2] == [0.0, 8.0], segs2)
    d2 = c.get(f"/api/meetings/{mid2}", headers=A).json()
    check("live : durée 16 s, statut done", d2["duration_seconds"] == 16 and d2["status"] == "done", d2)
    check("live : Whisper en détection auto (None)", calls["live_language"] is None)

    # déconnexion en plein live : le transcript doit être conservé
    mid3 = c.post("/api/meetings/create", json={"title": "Coupée"}, headers=A).json()["id"]
    with c.websocket_connect(f"/api/live/meeting/{mid3}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        ws.receive_json(); ws.send_bytes(b"\x01" * 500); ws.receive_json()
    import time
    for _ in range(100):  # le serveur continue l'analyse après la déconnexion : on attend jusqu'à 10 s
        d3 = c.get(f"/api/meetings/{mid3}", headers=A).json()
        if d3["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    check("live coupé : transcript sauvegardé", bool(d3.get("raw_text")), d3)
    check("live coupé : l'analyse est confiée au worker et va au bout (done + décisions)", d3["status"] == "done" and d3["decisions"], d3)

# --- fournisseur Ollama ---
import httpx
from app.services import llm_provider as lp
from app.config import settings
settings.llm_provider = "ollama"; lp.get_llm.cache_clear()
captured = {}
def fake_post(url, json=None, timeout=None):
    captured.update(url=url, payload=json)
    return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"message": {"content": '{"ok": 1}'}})
httpx.post = fake_post
out = lp.get_llm().chat([{"role": "user", "content": "hi"}], json_mode=True, max_tokens=100)
check("Ollama : endpoint /api/chat, format=json, réponse lue", captured["url"].endswith("/api/chat") and captured["payload"]["format"] == "json" and out == '{"ok": 1}', captured)
settings.llm_provider = "inconnu"; lp.get_llm.cache_clear()
try: lp.get_llm(); check("provider inconnu -> erreur claire", False)
except RuntimeError as e: check("provider inconnu -> erreur claire", "inconnu" in str(e))

# nettoyage : fichiers audio créés pendant le test + base temporaire
for _f in set(glob.glob(os.path.join("uploads", "*"))) - _before:
    os.remove(_f)
import app.database as _db
_db.engine.dispose()
try:
    os.remove("smoke_test.db")
except OSError:
    pass
print("\nRESULTAT GLOBAL :", "TOUT PASSE" if ok else "ECHEC")
sys.exit(0 if ok else 1)
