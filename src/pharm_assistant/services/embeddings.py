"""Lazy local embedding provider."""

from __future__ import annotations

from threading import Lock
from typing import Protocol


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""


class SentenceTransformerEmbedder:
    """Load a SentenceTransformer model only when retrieval first needs it."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: object | None = None
        self._load_lock = Lock()

    def _get_model(self) -> object:
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(  # type: ignore[attr-defined]
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()
