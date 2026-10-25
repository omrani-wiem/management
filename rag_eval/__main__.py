"""Usage (à la racine du projet) :
    python -m rag_eval --user ton@email.com --dataset rag_eval/qa.json
    python -m rag_eval --user ton@email.com --dataset rag_eval/qa.json --no-llm     # recherche seule, gratuit
"""
import argparse
import json
import os
import sys
from datetime import datetime

from rag_eval.runner import KS, evaluate, format_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Évalue le RAG sur tes réunions.")
    parser.add_argument("--user", required=True, help="email du compte dont on évalue les réunions")
    parser.add_argument("--dataset", required=True, help="fichier JSON de questions (voir rag_eval/README.md)")
    parser.add_argument("--k", type=int, default=5, help="nombre de passages récupérés (défaut 5)")
    parser.add_argument("--no-llm", action="store_true", help="ne mesurer que la recherche (aucun appel au LLM)")
    parser.add_argument("--out", help="fichier de rapport JSON (défaut : rag_eval/reports/<date>.json)")
    args = parser.parse_args()

    from app.config import settings
    from app.database import SessionLocal
    from app.models.user import User
    from app.services import rag

    with open(args.dataset, encoding="utf-8") as f:
        dataset = json.load(f)

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == args.user.lower()).first()
        if user is None:
            print(f"Utilisateur introuvable : {args.user}")
            return 1

        def search_fn(question: str) -> list[dict]:
            return rag.search_chunks(db, user.id, question, top_k=max(args.k, max(KS)))

        def ask_fn(question: str) -> dict:
            return rag.answer_question(db, user.id, question, top_k=args.k)

        report = evaluate(dataset, search_fn, None if args.no_llm else ask_fn)

    report["config"] = {
        "embedding_model": settings.embedding_model, "llm_provider": settings.llm_provider,
        "rag_chunk_chars": settings.rag_chunk_chars, "rag_top_k": args.k,
        "rag_min_similarity": settings.rag_min_similarity, "date": datetime.now().isoformat(timespec="seconds"),
    }
    print(format_report(report))
    out = args.out or os.path.join("rag_eval", "reports", datetime.now().strftime("%Y%m%d_%H%M%S") + ".json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nRapport enregistré : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
