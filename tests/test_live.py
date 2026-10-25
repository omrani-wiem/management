import json

from app.routers import live as live_router


def fake_chunks(monkeypatch, language="en"):
    state = {"n": 0, "spoken": "<non appelé>"}

    def fake(chunk, fmt, spoken):
        state["n"] += 1
        state["spoken"] = spoken
        return {"text": f"phrase {state['n']}", "segments": [{"start": 0.0, "end": 4.0, "text": f"phrase {state['n']}"}],
                "duration": 8.0, "language": language}

    monkeypatch.setattr(live_router, "transcribe_chunk", fake)
    return state


def token_of(headers):
    return headers["Authorization"].split()[1]


def new_live(client, headers, **body):
    return client.post("/api/meetings/create", json={"title": "Live", **body}, headers=headers).json()["id"]


def test_bad_token_and_non_json_first_message(client, alice):
    mid = new_live(client, alice)
    with client.websocket_connect(f"/api/live/meeting/{mid}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "bidon"}))
        assert ws.receive_json()["message"] == "Token invalide"
    with client.websocket_connect(f"/api/live/meeting/{mid}") as ws:
        ws.send_bytes(b"\x00" * 50)
        assert ws.receive_json()["message"] == "Authentification requise"


def test_other_users_meeting_and_garbage_id_refused(client, alice, bob):
    mid = new_live(client, alice)
    for target in (mid, "pas-un-uuid"):
        with client.websocket_connect(f"/api/live/meeting/{target}") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": token_of(bob)}))
            assert ws.receive_json()["type"] == "error"


def test_full_live_session(client, pipeline, alice, monkeypatch):
    state = fake_chunks(monkeypatch, language="en")
    mid = new_live(client, alice)
    with client.websocket_connect(f"/api/live/meeting/{mid}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token_of(alice), "format": "file"}))
        assert ws.receive_json()["type"] == "status"
        for _ in range(2):
            ws.send_bytes(b"\x01" * 500)
            assert ws.receive_json()["type"] == "transcript"
        ws.send_text(json.dumps({"type": "stop"}))
        msgs = []
        while not msgs or msgs[-1]["type"] not in ("done", "error"):
            msgs.append(ws.receive_json())
    done = msgs[-1]
    assert done["type"] == "done" and done["decisions"] and done["tasks"]
    assert done["language"] == "en" and done["output_language"] == "en"
    assert state["spoken"] is None                                     # langue auto -> Whisper détecte

    segs = client.get(f"/api/meetings/{mid}/segments", headers=alice).json()
    assert [s["start_seconds"] for s in segs] == [0.0, 8.0]            # 2e morceau décalé de la durée du 1er
    d = client.get(f"/api/meetings/{mid}", headers=alice).json()
    assert d["status"] == "done" and d["duration_seconds"] == 16 and d["summary"]


def test_declared_language_is_passed_to_whisper(client, pipeline, alice, monkeypatch):
    state = fake_chunks(monkeypatch)
    mid = new_live(client, alice, language="ar")
    with client.websocket_connect(f"/api/live/meeting/{mid}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token_of(alice)}))
        ws.receive_json()
        ws.send_bytes(b"\x01" * 500)
        ws.receive_json()
    assert state["spoken"] == "ar"


def test_disconnect_hands_analysis_to_worker(client, pipeline, alice, monkeypatch):
    fake_chunks(monkeypatch)
    mid = new_live(client, alice)
    with client.websocket_connect(f"/api/live/meeting/{mid}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token_of(alice)}))
        ws.receive_json()
        ws.send_bytes(b"\x01" * 500)
        ws.receive_json()
        # le client part brutalement, sans envoyer "stop"
    assert len(pipeline.worker_results) == 1                          # le worker a été sollicité
    d = client.get(f"/api/meetings/{mid}", headers=alice).json()
    assert d["raw_text"] == "phrase 1" and d["status"] == "done" and d["decisions"]
    assert pipeline.transcribe_calls == 0                             # il n'a PAS retranscrit : il a repris le texte


def test_no_audio_marks_meeting_failed(client, pipeline, alice, monkeypatch):
    fake_chunks(monkeypatch)
    mid = new_live(client, alice)
    with client.websocket_connect(f"/api/live/meeting/{mid}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token_of(alice)}))
        ws.receive_json()
        ws.send_text(json.dumps({"type": "stop"}))
        assert ws.receive_json()["message"] == "Aucune parole détectée"
    assert client.get(f"/api/meetings/{mid}", headers=alice).json()["status"] == "failed"


def test_llm_failure_keeps_transcript(client, pipeline, alice, monkeypatch):
    fake_chunks(monkeypatch)
    pipeline.llm_error = RuntimeError("LLM down")
    mid = new_live(client, alice)
    with client.websocket_connect(f"/api/live/meeting/{mid}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token_of(alice)}))
        ws.receive_json()
        ws.send_bytes(b"\x01" * 500)
        ws.receive_json()
        ws.send_text(json.dumps({"type": "stop"}))
        msgs = [ws.receive_json(), ws.receive_json()]
    assert msgs[-1]["type"] == "error" and "analyse a échoué" in msgs[-1]["message"]
    d = client.get(f"/api/meetings/{mid}", headers=alice).json()
    assert d["status"] == "failed" and d["raw_text"] == "phrase 1"
