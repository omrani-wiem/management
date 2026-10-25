import time
from typing import Callable

from rag_eval.metrics import first_relevant_rank, is_relevant, keywords_found, ratio

KS = (1, 3, 5)


def _failure(q: dict, problem: str, **extra) -> dict:
    return {"id": q.get("id"), "question": q["question"], "problem": problem, **extra}


def evaluate(
    dataset: list[dict],
    search_fn: Callable[[str], list[dict]],
    ask_fn: Callable[[str], dict] | None = None,
    ks: tuple[int, ...] = KS,
) -> dict:
    """Évalue un jeu de questions.

    search_fn(question) -> liste de passages (dicts avec `text`, `meeting_title`...), du plus au moins pertinent.
    ask_fn(question)    -> {"answer", "answerable", "sources": [...]}   (optionnel : sans lui, on ne mesure que la recherche)

    Format d'une question :
      {"id", "question", "answerable": true|false,
       "evidence": ["phrase exacte présente dans le bon passage", ...],     # pour answerable=true
       "answer_keywords": ["mot", ...],                                       # optionnel : mots attendus dans la réponse
       "meeting_title": "Titre"}                                              # optionnel : le bon passage doit venir de là
    """
    answerable = [q for q in dataset if q.get("answerable", True)]
    unanswerable = [q for q in dataset if not q.get("answerable", True)]
    with_evidence = [q for q in answerable if q.get("evidence")]

    failures: list[dict] = []

    # ---------- recherche ----------
    hits = {k: 0 for k in ks}
    reciprocal_ranks: list[float] = []
    for q in with_evidence:
        rank = first_relevant_rank(search_fn(q["question"]), q)
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        for k in ks:
            if rank is not None and rank <= k:
                hits[k] += 1
        if rank is None or rank > max(ks):
            failures.append(_failure(q, "passage pertinent non retrouvé", rank=rank))
    retrieval = {
        "questions_evaluated": len(with_evidence),
        **{f"hit@{k}": ratio(hits[k], len(with_evidence)) for k in ks},
        "mrr": ratio(sum(reciprocal_ranks), len(with_evidence)),
    }

    # ---------- réponses ----------
    answers = None
    if ask_fn is not None:
        correct_refusals = false_refusals = 0
        keyword_ok = keyword_total = 0
        precisions: list[float] = []
        latencies: list[float] = []
        for q in dataset:
            started = time.perf_counter()
            result = ask_fn(q["question"])
            latencies.append(time.perf_counter() - started)

            if not q.get("answerable", True):
                if not result["answerable"]:
                    correct_refusals += 1
                else:
                    failures.append(_failure(q, "aurait dû refuser de répondre", answer=result["answer"]))
                continue

            if not result["answerable"]:
                false_refusals += 1
                failures.append(_failure(q, "a refusé alors que l'information existe"))
                continue
            if q.get("answer_keywords"):
                keyword_total += 1
                if keywords_found(result["answer"], q["answer_keywords"]):
                    keyword_ok += 1
                else:
                    failures.append(_failure(q, "mots-clés attendus absents de la réponse", answer=result["answer"]))
            if q.get("evidence") and result["sources"]:
                precisions.append(sum(is_relevant(s, q) for s in result["sources"]) / len(result["sources"]))
        answers = {
            "answerable_questions": len(answerable),
            "unanswerable_questions": len(unanswerable),
            "correct_refusal_rate": ratio(correct_refusals, len(unanswerable)),
            "false_refusal_rate": ratio(false_refusals, len(answerable)),
            "keyword_accuracy": ratio(keyword_ok, keyword_total),
            "citation_precision": ratio(sum(precisions), len(precisions)),
            "avg_latency_s": round(sum(latencies) / len(latencies), 2) if latencies else None,
        }

    return {"n_questions": len(dataset), "retrieval": retrieval, "answers": answers, "failures": failures}


def format_report(report: dict) -> str:
    lines = [f"Questions : {report['n_questions']}", "", "RECHERCHE (passage pertinent dans les k premiers)"]
    for key, value in report["retrieval"].items():
        lines.append(f"  {key:22s} {value}")
    if report["answers"]:
        lines += ["", "RÉPONSES"]
        for key, value in report["answers"].items():
            lines.append(f"  {key:22s} {value}")
    if report["failures"]:
        lines += ["", f"ÉCHECS ({len(report['failures'])})"]
        for f in report["failures"]:
            lines.append(f"  - [{f.get('id')}] {f['problem']} : {f['question']}")
    return "\n".join(lines)
