"""Embed stage — sentence-transformers MiniLM.

`Embedder` is callable (implements the `EmbedFn` protocol that
`pipeline.stages.filter.SemanticFilter` accepts), so the same instance can
be reused for the semantic filter and downstream clustering. The model is
loaded lazily on first call, keeping `import pipeline.stages.embed` cheap.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from pipeline.config import EMBEDDING_DIM, EMBEDDING_MODEL

log = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 64


class Embedder:
    """Wraps a sentence-transformers model behind a stable `__call__` signature."""

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model: Any = None

    def __call__(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        model = self._get_model()
        vecs = model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            log.info("embed: loading model %s", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model
