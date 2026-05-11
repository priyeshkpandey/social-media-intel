"""Filter precision/recall evaluation against a small labeled fixture.

Runs as a pytest module — see `pyproject.toml` testpaths. Asserts:
  * cheap_pass keeps every `keep` post (recall on real pain points).
  * cheap_pass drops every `drop` post tagged `spam` (precision on obvious junk).

Posts labeled `drop` with category `needs_semantic` are deliberately not
asserted here — they're expected to pass cheap_pass and be cut by the
semantic stage. That eval lives in Step 6 once embeddings are wired up.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.stages.filter import cheap_pass

_FIXTURE = Path(__file__).parent / "fixtures" / "labeled_posts.json"


def _load() -> list[dict]:
    return json.loads(_FIXTURE.read_text())


def test_cheap_pass_recall_on_labeled_keep() -> None:
    """Every labeled-keep post must pass the cheap filter."""
    posts = _load()
    keep = [p for p in posts if p["label"] == "keep"]
    assert keep, "fixture missing keep examples"
    missed = [p for p in keep if not cheap_pass(p["text"])]
    assert not missed, (
        f"cheap_pass dropped {len(missed)}/{len(keep)} keep examples: "
        + ", ".join(p["note"] for p in missed)
    )


def test_cheap_pass_blocks_spam() -> None:
    """Every labeled-spam post must be dropped by the cheap filter."""
    posts = _load()
    spam = [p for p in posts if p["label"] == "drop" and p.get("category") == "spam"]
    assert spam, "fixture missing spam examples"
    leaked = [p for p in spam if cheap_pass(p["text"])]
    assert not leaked, (
        f"cheap_pass let through {len(leaked)}/{len(spam)} spam: "
        + ", ".join(p["note"] for p in leaked)
    )
