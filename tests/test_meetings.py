import os
import uuid

import pytest

from app.routers import meetings as meetings_router
from tests.conftest import WAV


def test_upload_is_processed_and_detail_has_summary(client, pipeline, upload, alice):
    r = upload(alice, participants="Ali, Sara", language="ar", output_language="en")
    assert r.status_code == 200
    assert pipeline.worker_results[0].result["status"] == "done"

    d = client.get(f"/api/meetings/{r.json()['id']}", headers=alice).json()
    # non-régression : le détail DOIT contenir résumé et transcription
    assert d["status"] == "done"
    assert d["summary"] == "Résumé test"
    assert "PostgreSQL" in d["raw_text"]
    assert d["language"] == "ar" and d["output_language"] == "en"
    assert d["duration_seconds"] == 20


def test_typed_participants_are_kept_and_detected_ones_added(client, pipeline, upload, alice):
    mid = upload(alice, participants="Ali, Sara").json()["id"]
    participants = client.get(f"/api/meetings/{mid}", headers=alice).json()["participants"]
    assert "Sara" in participants and "Ali Ben Salah" in participants and "Ali" in participants


def test_segments_endpoint(client, pipeline, upload, alice):
    mid = upload(alice).json()["id"]
    segs = client.get(f"/api/meetings/{mid}/segments", headers=alice).json()
    assert [s["start_seconds"] for s in segs] == [0.0, 5.0, 12.5]


@pytest.mark.parametrize("kwargs,expected", [
    ({"filename": "notes.txt"}, 400),                              # extension interdite
    ({"filename": "faux.mp3", "content": b"ceci est du texte brut..."}, 400),   # contenu non audio
    ({"language": "klingon"}, 400),
    ({"output_language": "es"}, 400),
])
def test_invalid_uploads_rejected(client, pipeline, upload, alice, kwargs, expected):
    assert upload(alice, **kwargs).status_code == expected


def test_too_large_upload_rejected_and_file_removed(client, pipeline, upload, alice, monkeypatch):
    monkeypatch.setattr(meetings_router, "MAX_BYTES", 100)
    before = set(os.listdir(meetings_router.UPLOAD_DIR))
    assert upload(alice, content=WAV + b"\x00" * 500).status_code == 413
    assert set(os.listdir(meetings_router.UPLOAD_DIR)) == before


def test_client_filename_is_never_used_in_path(client, pipeline, upload, alice):
    r = upload(alice, filename="../../evil name.wav")
    assert r.status_code == 200
    from app.database import SessionLocal
    from app.models.meeting import Meeting

    with SessionLocal() as db:
        path = db.get(Meeting, uuid.UUID(r.json()["id"])).audio_path
    assert os.path.dirname(path) == meetings_router.UPLOAD_DIR
    stem = os.path.splitext(os.path.basename(path))[0]
    uuid.UUID(stem)  # le nom est un UUID généré par le serveur


def test_queue_down_returns_503_and_marks_meeting_failed(client, pipeline, upload, alice):
    pipeline.delay_error = ConnectionError("redis down")
    assert upload(alice).status_code == 503
    meetings = client.get("/api/meetings/", headers=alice).json()
    assert meetings[0]["status"] == "failed"


def test_list_is_paginated_and_newest_first(client, alice):
    for i in range(3):
        client.post("/api/meetings/create", json={"title": f"R{i}"}, headers=alice)
    assert len(client.get("/api/meetings/?limit=2", headers=alice).json()) == 2
    titles = [m["title"] for m in client.get("/api/meetings/", headers=alice).json()]
    assert titles[0] == "R2"
    assert client.get("/api/meetings/?limit=0", headers=alice).status_code == 422


def test_create_live_meeting_validates_languages(client, alice):
    ok = client.post("/api/meetings/create", json={"title": "Live", "language": "ar", "output_language": "fr"}, headers=alice)
    assert ok.status_code == 200 and ok.json()["language"] == "ar"
    assert client.post("/api/meetings/create", json={"title": "Live", "language": "xx"}, headers=alice).status_code == 422
