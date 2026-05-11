"""Unit tests for pipeline.stages.embed."""

from __future__ import annotations

import sys

import numpy as np
import pytest

from pipeline.config import EMBEDDING_DIM
from pipeline.stages import embed


class _FakeSentenceTransformer:
    instances: list[str] = []

    def __init__(self, name: str) -> None:
        _FakeSentenceTransformer.instances.append(name)
        self.name = name

    def encode(
        self,
        texts: list[str],
        batch_size: int = 64,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = False,
    ) -> np.ndarray:
        return np.array(
            [[float(len(t)), float(hash(t) % 100)] for t in texts],
            dtype=np.float32,
        )


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    _FakeSentenceTransformer.instances.clear()


@pytest.fixture
def _stub_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    mod = types.ModuleType("sentence_transformers")
    mod.SentenceTransformer = _FakeSentenceTransformer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", mod)


def test_embedder_empty_input_returns_zero_shape() -> None:
    e = embed.Embedder()
    out = e([])
    assert out.shape == (0, EMBEDDING_DIM)
    assert out.dtype == np.float32


def test_embedder_lazy_loads_model_once(_stub_sentence_transformers: None) -> None:
    e = embed.Embedder(model_name="fake-model")
    e(["hello", "world"])
    e(["another"])
    assert _FakeSentenceTransformer.instances == ["fake-model"]


def test_embedder_returns_numpy_with_expected_shape(_stub_sentence_transformers: None) -> None:
    e = embed.Embedder()
    out = e(["abc", "defg"])
    assert isinstance(out, np.ndarray)
    assert out.shape == (2, 2)
    assert out.dtype == np.float32
