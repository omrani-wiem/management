"""Fonctions de mesure (pures, sans base de données ni LLM : faciles à tester)."""
import unicodedata


def normalize(s: str) -> str:
    """minuscules, sans accents ni voyelles arabes, espaces normalisés."""
    s = unicodedata.normalize("NFKD", s or "")
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).lower().split())


def is_relevant(chunk: dict, question: dict) -> bool:
    """Un passage est pertinent s'il contient (au moins) une des phrases `evidence` de la question
    et, si `meeting_title` est indiqué, s'il vient de cette réunion."""
    evidence = question.get("evidence") or []
    if not evidence:
        return False
    wanted_title = question.get("meeting_title")
    if wanted_title and normalize(wanted_title) != normalize(chunk.get("meeting_title", "")):
        return False
    text = normalize(chunk.get("text", ""))
    return any(normalize(e) in text for e in evidence)


def first_relevant_rank(chunks: list[dict], question: dict) -> int | None:
    """Rang (à partir de 1) du premier passage pertinent, ou None."""
    for rank, chunk in enumerate(chunks, start=1):
        if is_relevant(chunk, question):
            return rank
    return None


def keywords_found(answer: str, keywords: list[str]) -> bool:
    """Tous les mots-clés attendus figurent dans la réponse (ignore casse et accents)."""
    text = normalize(answer)
    return all(normalize(k) in text for k in keywords)


def ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 3) if denominator else None
