"""Embeddings de test : déterministes, sans téléchargement de modèle.
Chaque mot (sans accents, ≥ 3 lettres) est projeté sur une dimension : la similarité cosinus reflète
le nombre de mots en commun. Suffisant pour tester toute la mécanique (pgvector, RRF, seuils, citations)."""
import hashlib
import math
import re
import unicodedata

DIM = 384


def tokens(text: str) -> list[str]:
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return [t for t in re.findall(r"\w+", s) if len(t) >= 3]


class HashingEmbedder:
    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for tok in tokens(text):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            v[0], norm = 1.0, 1.0
        return [x / norm for x in v]

    def embed_passages(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)
