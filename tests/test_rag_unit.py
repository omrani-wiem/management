"""RAG : logique pure et garde-fous (ne nécessite pas PostgreSQL)."""
import pytest
from pydantic import ValidationError

from app.config import settings
from app.services import rag
from app.services.rag import (
    AnswerPayload,
    build_or_tsquery,
    chunk_segments,
    chunk_text,
    detect_language,
    refusal_message,
    validate_payload,
)


def seg(i, text="x" * 40):
    return {"start": i * 10.0, "end": i * 10.0 + 9, "text": text}


# ---------------------------------------------------------------- découpage

def test_chunking_covers_everything_with_overlap_and_timestamps():
    segments = [seg(i, f"segment numéro {i} " + "mot " * 8) for i in range(10)]
    chunks = chunk_segments(segments, max_chars=120, overlap=1)
    assert len(chunks) > 1
    assert chunks[0]["start"] == 0.0 and chunks[-1]["end"] == 99.0
    assert [c["idx"] for c in chunks] == list(range(len(chunks)))
    covered = " ".join(c["text"] for c in chunks)
    assert all(f"segment numéro {i} " in covered for i in range(10))             # rien n'est perdu
    second = segments[1]["text"].strip()
    assert second in chunks[0]["text"] and second in chunks[1]["text"]           # chevauchement d'un segment


@pytest.mark.parametrize("max_chars,overlap", [(10, 1), (10, 0), (1000, 1), (60, 3)])
def test_chunking_always_terminates_and_never_returns_empty_chunks(max_chars, overlap):
    chunks = chunk_segments([seg(i) for i in range(25)], max_chars=max_chars, overlap=overlap)
    assert chunks and all(c["text"].strip() for c in chunks)
    assert chunks[-1]["end"] == 24 * 10.0 + 9


def test_chunking_ignores_empty_segments_and_handles_no_input():
    assert chunk_segments([], 100) == []
    assert chunk_segments([{"start": 0, "end": 1, "text": "  "}], 100) == []


def test_one_oversized_segment_is_kept_whole():
    chunks = chunk_segments([seg(0, "a" * 500)], max_chars=100)
    assert len(chunks) == 1 and len(chunks[0]["text"]) == 500


def test_text_fallback_for_old_meetings_has_no_timestamps():
    chunks = chunk_text("Première phrase. Deuxième phrase ! Troisième phrase ? " * 20, max_chars=150)
    assert len(chunks) > 1
    assert all(c["start"] is None and c["end"] is None for c in chunks)
    assert chunk_text("", 100) == []


# ---------------------------------------------------------------- recherche par mots-clés

def test_or_tsquery_drops_stopwords_and_short_words_and_is_safe():
    assert build_or_tsquery("Qui doit envoyer le devis ?") == "doit | envoyer | devis"
    assert build_or_tsquery("What was the budget for Tunis?") == "budget | tunis"
    assert build_or_tsquery("PO-4821") == "4821"
    assert build_or_tsquery("qui ? le la") is None
    assert build_or_tsquery("'); DROP TABLE users; --") == "drop | table | users"   # aucun opérateur ne passe
    assert build_or_tsquery("  ") is None


# ---------------------------------------------------------------- garde-fous de la réponse

def payload(**kw):
    return AnswerPayload.model_validate({"answerable": True, "answer": "ok [1]", "citations": [1], **kw})


def test_valid_payload_passes():
    validate_payload(payload(), n_sources=3)
    validate_payload(AnswerPayload(answerable=False, answer="", citations=[]), n_sources=3)


@pytest.mark.parametrize("bad", [
    {"citations": []},                                # réponse positive sans citation
    {"citations": [4]},                               # source inexistante
    {"citations": [0]},
    {"answer": "Selon la source [7]"},                # renvoi vers une source inexistante dans le texte
    {"answer": "   "},
])
def test_hallucination_guard_rejects_unsupported_answers(bad):
    with pytest.raises(ValueError):
        validate_payload(payload(**bad), n_sources=3)


def test_payload_coercion_is_tolerant():
    p = AnswerPayload.model_validate({"answerable": "true", "answer": "x", "citations": ["[2]", "1", 2, None]})
    assert p.answerable is True and p.citations == [2, 1]
    assert AnswerPayload.model_validate({"answerable": "false", "citations": None}).answerable is False
    with pytest.raises(ValidationError):
        AnswerPayload.model_validate({"answer": "pas de champ answerable"})


def test_language_detection_and_refusal_messages():
    assert detect_language("ما هي عاصمة أستراليا؟") == "ar"
    assert detect_language("What was decided about the budget?") == "en"
    assert detect_language("Quel budget a été décidé ?") == "fr"
    assert refusal_message("Quelle est la date ?") == "Je ne trouve pas cette information dans tes réunions."
    assert "can't find" in refusal_message("When is the deadline?")


# ---------------------------------------------------------------- API : validation, désactivation, authentification

@pytest.mark.parametrize("body", [{"question": "ab"}, {"question": "x" * 1001}, {"question": "valide ?", "top_k": 0},
                                  {"question": "valide ?", "top_k": 13}, {"question": "valide ?", "meeting_id": "pas-un-uuid"}])
def test_ask_validates_input(client, alice, body):
    assert client.post("/api/rag/ask", json=body, headers=alice).status_code == 422


def test_rag_endpoints_return_503_when_disabled(client, alice, monkeypatch):
    monkeypatch.setattr(settings, "rag_enabled", False)
    assert client.post("/api/rag/ask", json={"question": "Une question ?"}, headers=alice).status_code == 503
    assert client.post("/api/rag/search", json={"question": "Une question ?"}, headers=alice).status_code == 503
    assert client.post("/api/rag/reindex", headers=alice).status_code == 503
    status = client.get("/api/rag/status", headers=alice).json()
    assert status["enabled"] is False and status["chunks_total"] == 0


def test_dimension_mismatch_gives_actionable_error(monkeypatch):
    from app.services import embeddings

    class FakeModel:
        def embed(self, texts, batch_size=32):
            import numpy as np
            return [np.zeros(768) for _ in texts]

    emb = embeddings.FastEmbedEmbedder.__new__(embeddings.FastEmbedEmbedder)
    emb._model, emb._query_prefix, emb._passage_prefix = FakeModel(), "", ""
    import threading
    emb._lock = threading.Lock()
    with pytest.raises(RuntimeError, match="dimension 768"):
        emb.embed_query("test")


def test_rag_module_exposes_one_llm_entry_point():
    assert callable(rag._llm)   # point d'injection unique (utilisé par les tests)
