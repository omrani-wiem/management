"""Le module d'évaluation : métriques et orchestration (avec de fausses fonctions de recherche / réponse)."""
from rag_eval.metrics import first_relevant_rank, is_relevant, keywords_found, normalize, ratio
from rag_eval.runner import evaluate, format_report

CHUNKS = [
    {"meeting_title": "A", "text": "Rien d'utile ici."},
    {"meeting_title": "Sprint", "text": "Ali enverra le devis au client avant vendredi."},
    {"meeting_title": "B", "text": "Le budget est de 5000 euros."},
]


def test_normalize_and_ratio():
    assert normalize("  Élève   À  L'ÉCOLE ") == "eleve a l'ecole"
    assert ratio(1, 3) == 0.333 and ratio(1, 0) is None


def test_relevance_uses_evidence_and_optional_meeting():
    q = {"evidence": ["ENVERRA le devis"]}
    assert is_relevant(CHUNKS[1], q) and not is_relevant(CHUNKS[0], q)
    assert not is_relevant(CHUNKS[1], {**q, "meeting_title": "Autre"})
    assert is_relevant(CHUNKS[1], {**q, "meeting_title": "sprint"})
    assert not is_relevant(CHUNKS[1], {"question": "sans preuve"})
    assert first_relevant_rank(CHUNKS, q) == 2 and first_relevant_rank(CHUNKS, {"evidence": ["introuvable"]}) is None


def test_keywords():
    assert keywords_found("Le budget est de 5 000 euros, validé par Hélène", ["helene", "euros"])
    assert not keywords_found("Rien", ["budget"])


DATASET = [
    {"id": "q1", "question": "Qui envoie le devis ?", "answerable": True,
     "evidence": ["enverra le devis"], "answer_keywords": ["Ali"]},
    {"id": "q2", "question": "Quel budget ?", "answerable": True, "evidence": ["5000 euros"], "answer_keywords": ["5000"]},
    # q3 : le passage pertinent n'est jamais retrouvé
    {"id": "q3", "question": "Quand le salon ?", "answerable": True, "evidence": ["salon de Tunis"]},
    {"id": "q4", "question": "Capitale de l'Australie ?", "answerable": False},
    {"id": "q5", "question": "Poids de la Lune ?", "answerable": False},
]


def fake_search(question):
    return CHUNKS


def fake_ask(question):
    if question.startswith("Qui"):
        return {"answerable": True, "answer": "Ali s'en charge [1].", "sources": [CHUNKS[1]]}
    if question.startswith("Quel"):
        # mauvais montant, et 1 source sur 2 seulement est pertinente
        return {"answerable": True, "answer": "Environ 4000 euros [1].", "sources": [CHUNKS[2], CHUNKS[0]]}
    if question.startswith("Quand"):
        return {"answerable": False, "answer": "Je ne sais pas.", "sources": []}                              # refus à tort
    if question.startswith("Capitale"):
        return {"answerable": False, "answer": "Introuvable.", "sources": []}                                 # bon refus
    return {"answerable": True, "answer": "La Lune pèse beaucoup [1].", "sources": [CHUNKS[0]]}               # aurait dû refuser


def test_full_evaluation_numbers():
    report = evaluate(DATASET, fake_search, fake_ask, ks=(1, 3))
    r, a = report["retrieval"], report["answers"]
    assert r["questions_evaluated"] == 3
    assert r["hit@1"] == 0.0 and r["hit@3"] == 0.667                      # q1 rang 2, q2 rang 3, q3 jamais
    assert r["mrr"] == round((1 / 2 + 1 / 3 + 0) / 3, 3)
    assert a["correct_refusal_rate"] == 0.5 and a["false_refusal_rate"] == 0.333
    assert a["keyword_accuracy"] == 0.5                                    # q1 ok, q2 mauvais montant
    assert a["citation_precision"] == 0.75                                 # (1 + 0.5) / 2
    problems = {f["problem"] for f in report["failures"]}
    assert {"passage pertinent non retrouvé", "aurait dû refuser de répondre",
            "a refusé alors que l'information existe", "mots-clés attendus absents de la réponse"} <= problems


def test_retrieval_only_mode_and_report_text():
    report = evaluate(DATASET, fake_search, None, ks=(1, 3))
    assert report["answers"] is None
    text = format_report(report)
    assert "hit@3" in text and "RÉPONSES" not in text
    assert "RÉPONSES" in format_report(evaluate(DATASET, fake_search, fake_ask, ks=(1, 3)))


def test_empty_dataset_does_not_crash():
    report = evaluate([], fake_search, fake_ask)
    assert report["n_questions"] == 0 and report["retrieval"]["hit@1"] is None
