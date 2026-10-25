"""Embeddings multilingues (FR / EN / AR) via FastEmbed (ONNX, sans PyTorch).
Le modèle est chargé à la demande, une seule fois par processus (le téléchargement a lieu au premier usage)."""
import logging
import threading
from functools import lru_cache
from typing import Protocol

from app.config import settings
from app.models.chunk import EMBEDDING_DIM

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    def __init__(self) -> None:
        from fastembed import TextEmbedding  # import tardif

        name = settings.embedding_model
        logger.info("Chargement du modèle d'embedding '%s'", name)
        kwargs = {"cache_dir": settings.embedding_cache_dir} if settings.embedding_cache_dir else {}
        self._model = TextEmbedding(model_name=name, **kwargs)
        self._lock = threading.Lock()
        # les modèles e5 exigent ces préfixes (FastEmbed ne les ajoute pas)
        is_e5 = "e5" in name.lower()
        self._query_prefix = "query: " if is_e5 else ""
        self._passage_prefix = "passage: " if is_e5 else ""

    def _embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            vectors = [v.tolist() for v in self._model.embed(texts, batch_size=32)]
        if vectors and len(vectors[0]) != EMBEDDING_DIM:
            raise RuntimeError(
                f"Le modèle '{settings.embedding_model}' produit des vecteurs de dimension {len(vectors[0])}, "
                f"mais la base attend {EMBEDDING_DIM}. Crée une migration pour changer la dimension, "
                "puis réindexe les réunions."
            )
        return vectors

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._embed([self._passage_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._embed([self._query_prefix + text])[0]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    return FastEmbedEmbedder()
