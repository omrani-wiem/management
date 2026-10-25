import json
from datetime import date

import pytest

import app.services.ai_processor as ap
from app.schemas.meeting import parse_timestamp

GOOD = {"summary": "Résumé", "participants_detected": ["Ali"], "decisions": [], "tasks": [
    {"title": "Faire X", "assignee": "Ali", "confidence": 0.9, "priority": "high"}]}


def script_llm(monkeypatch, replies):
    """Le LLM renvoie successivement les réponses de la liste ; on enregistre les appels."""
    calls = []

    def fake(messages, json_mode, max_tokens=2000):
        calls.append({"messages": messages, "json_mode": json_mode})
        reply = replies[min(len(calls) - 1, len(replies) - 1)]
        return reply if isinstance(reply, str) else json.dumps(reply)

    monkeypatch.setattr(ap, "_llm", fake)
    return calls


def test_json_inside_code_fence_is_parsed(monkeypatch):
    script_llm(monkeypatch, ["```json\n" + json.dumps(GOOD) + "\n```"])
    assert ap.analyze_meeting("bonjour")["tasks"][0]["title"] == "Faire X"


def test_invalid_json_is_retried_then_succeeds(monkeypatch):
    calls = script_llm(monkeypatch, ["pas du json", '{"summary": ', GOOD])
    assert ap.analyze_meeting("bonjour")["summary"] == "Résumé"
    assert len(calls) == 3


def test_three_invalid_answers_raise(monkeypatch):
    script_llm(monkeypatch, ["nope"])
    with pytest.raises(ValueError):
        ap.analyze_meeting("bonjour")


def test_empty_transcript_rejected(monkeypatch):
    script_llm(monkeypatch, [GOOD])
    with pytest.raises(ValueError):
        ap.analyze_meeting("   \n  ")


def test_tolerant_to_sloppy_llm_output(monkeypatch):
    sloppy = {"summary": "S", "participants_detected": None,
              "decisions": ["Décision en simple texte", {"text": "Autre", "rationale": "null", "timestamp": "1:02:03"}],
              "tasks": [{"title": "T", "assignee": "null", "confidence": 7, "priority": "URGENT",
                         "due_date": "2026-12-24T10:00:00", "timestamp": "[00:30]"}]}
    script_llm(monkeypatch, [sloppy])
    r = ap.analyze_meeting("x")
    t = r["tasks"][0]
    assert r["participants_detected"] == []
    assert [d["text"] for d in r["decisions"]] == ["Décision en simple texte", "Autre"]
    assert r["decisions"][1]["timestamp"] == 3723 and r["decisions"][1]["rationale"] is None
    assert t["assignee"] is None and t["confidence"] == 1.0 and t["priority"] == "medium"
    assert t["due_date"] == date(2026, 12, 24) and t["timestamp"] == 30


@pytest.mark.parametrize("raw,expected", [
    ("12:30", 750), ("75:30", 4530), ("1:02:03", 3723), ("[00:05]", 5), (90, 90), (12.7, 12),
    (None, None), ("null", None), ("", None), ("abc", None), (True, None),
])
def test_parse_timestamp(raw, expected):
    assert parse_timestamp(raw) == expected


def test_output_language_in_prompt(monkeypatch):
    calls = script_llm(monkeypatch, [GOOD])
    ap.analyze_meeting("salut", output_language="ar")
    assert "in Arabic" in calls[0]["messages"][0]["content"]
    ap.analyze_meeting("salut", output_language="zz")          # inconnue -> français
    assert "in French" in calls[1]["messages"][0]["content"]


def test_long_transcript_is_chunked_merged_and_deduplicated(monkeypatch):
    def reply(messages, json_mode, max_tokens=2000):
        if json_mode:
            return json.dumps(GOOD | {"decisions": [{"text": "Même décision"}]})
        return "Résumé fusionné"

    monkeypatch.setattr(ap, "_llm", reply)
    long_text = "\n".join(f"[{i // 60:02d}:{i % 60:02d}] " + "mot " * 40 for i in range(300))
    assert len(ap._split_text(long_text, ap._chunk_chars())) > 1
    r = ap.analyze_meeting(long_text)
    assert r["summary"] == "Résumé fusionné"
    assert len(r["tasks"]) == 1 and len(r["decisions"]) == 1      # doublons entre morceaux supprimés


def test_split_text_keeps_lines_intact_and_splits_giant_lines():
    chunks = ap._split_text("ligne un\nligne deux\nligne trois", 20)
    assert chunks == ["ligne un\nligne deux", "ligne trois"]
    giant = ap._split_text("mot " * 100, 50)
    assert all(len(c) <= 50 for c in giant) and len(giant) > 1
