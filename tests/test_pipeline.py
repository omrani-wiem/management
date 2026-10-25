"""Le worker : langues, seuil de confiance, reprise après échec, idempotence."""
from app.models.meeting import Meeting
from app.services.meeting_pipeline import (
    format_timestamp,
    merge_names,
    resolve_output_language,
    resolve_spoken_language,
    timestamped_text,
)


def test_languages_are_propagated(client, pipeline, upload, alice):
    upload(alice, language="ar", output_language="en")
    assert pipeline.whisper_language == "ar"
    assert "in English" in pipeline.prompts[0][0]["content"]


def test_auto_language_uses_detection_and_output_follows_it(client, pipeline, upload, alice):
    pipeline.detected_language = "en"
    mid = upload(alice).json()["id"]          # language=auto
    assert pipeline.whisper_language is None  # Whisper détecte lui-même
    d = client.get(f"/api/meetings/{mid}", headers=alice).json()
    assert d["language"] == "en"
    assert "in English" in pipeline.prompts[0][0]["content"]


def test_llm_receives_timestamped_transcript_and_meeting_date(client, pipeline, upload, alice):
    from datetime import date

    upload(alice)
    user_prompt = pipeline.prompts[0][1]["content"]
    assert "[00:05] On décide" in user_prompt
    assert date.today().isoformat() in user_prompt


def test_task_details_confidence_priority_dates(client, pipeline, upload, alice):
    upload(alice)
    tasks = {t["title"]: t for t in client.get("/api/tasks/", headers=alice).json()}
    sure, vague = tasks["Envoyer le devis"], tasks["Tâche floue"]
    assert sure["assignee"] == "Ali Ben Salah" and sure["priority"] == "high" and sure["source_seconds"] == 12
    assert vague["assignee"] is None            # confiance 0.4 < 0.75
    assert vague["priority"] == "medium"        # "urgent" n'existe pas
    assert vague["due_date"] is None            # "demain" n'est pas une date


def test_decisions_are_saved_with_timestamp(client, pipeline, upload, alice):
    mid = upload(alice).json()["id"]
    decisions = client.get(f"/api/meetings/{mid}", headers=alice).json()["decisions"]
    assert decisions[0]["text"] == "Migrer vers PostgreSQL" and decisions[0]["source_seconds"] == 5


def test_failed_analysis_keeps_transcript_and_rerun_skips_transcription(client, pipeline, upload, alice):
    pipeline.llm_error = RuntimeError("Groq indisponible")
    mid = upload(alice).json()["id"]
    d = client.get(f"/api/meetings/{mid}", headers=alice).json()
    assert d["status"] == "failed" and d["raw_text"]       # la transcription est conservée
    assert pipeline.transcribe_calls == 1

    pipeline.llm_error = None                              # le LLM revient : on relance le worker
    pipeline.runner.delay(mid, [])
    d = client.get(f"/api/meetings/{mid}", headers=alice).json()
    assert d["status"] == "done" and d["summary"] == "Résumé test"
    assert pipeline.transcribe_calls == 1                  # PAS de nouvelle transcription


def test_rerun_does_not_duplicate_tasks_or_decisions(client, pipeline, upload, alice):
    mid = upload(alice).json()["id"]
    pipeline.runner.delay(mid, [])
    assert len(client.get(f"/api/tasks/meeting/{mid}", headers=alice).json()) == 2
    assert len(client.get(f"/api/meetings/{mid}", headers=alice).json()["decisions"]) == 1


def test_empty_transcription_fails_without_retry(client, pipeline, upload, alice):
    pipeline.segments = [{"start": 0.0, "end": 0.0, "text": ""}]
    mid = upload(alice).json()["id"]
    assert client.get(f"/api/meetings/{mid}", headers=alice).json()["status"] == "failed"
    assert pipeline.transcribe_calls == 1


def test_missing_audio_file_fails_cleanly(client, pipeline, upload, alice):
    from app.database import SessionLocal
    import uuid

    mid = client.post("/api/meetings/create", json={"title": "x"}, headers=alice).json()["id"]
    with SessionLocal() as db:
        db.get(Meeting, uuid.UUID(mid)).audio_path = "/chemin/inexistant.wav"
        db.commit()
    import app.workers.tasks as worker

    def raise_fnf(*a, **k):
        raise FileNotFoundError("absent")

    original = worker.transcribe_audio
    worker.transcribe_audio = raise_fnf
    try:
        result = pipeline.runner.delay(mid, [])
    finally:
        worker.transcribe_audio = original
    assert result.result == {"error": "Fichier audio introuvable"}
    assert client.get(f"/api/meetings/{mid}", headers=alice).json()["status"] == "failed"


def test_pure_helpers():
    assert merge_names(["Ali", "sara"], ["ALI", "Sara", "Karim"]) == ["Ali", "sara", "Karim"]
    assert format_timestamp(75.9) == "01:15" and format_timestamp(4530) == "75:30"
    assert timestamped_text([{"start": 3, "end": 4, "text": "Salut"}, {"start": 5, "end": 6, "text": ""}]) == "[00:03] Salut"

    class M:  # faux Meeting
        language, output_language = None, None

    m = M()
    assert resolve_spoken_language(m) is None
    m.language = "AR"
    assert resolve_spoken_language(m) == "ar" and resolve_output_language(m) == "ar"
    m.output_language = "en"
    assert resolve_output_language(m) == "en"
    m.language, m.output_language = "es", None
    assert resolve_output_language(m) == "fr"                       # langue non gérée -> français
    assert resolve_output_language(m, detected="ar") == "ar"
