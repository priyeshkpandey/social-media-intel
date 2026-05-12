"""Pipeline CLI orchestrator.

Wires every stage together. Invoked from the weekly GitHub Actions workflow
and from `make refresh` locally:

    uv run python -m pipeline.main --since 7d --out ./out

Stages run in this order:
  ingest → normalize → dedupe → cheap-filter → embed → semantic-filter
   → cluster → score → synthesize (env-gated) → export

`ClusterState` is persisted to `./.cache/cluster_state.parquet` between runs
so cluster IDs stay stable across weeks. The cache directory is restored +
saved by the GitHub Actions cache step.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipeline.config import CACHE_DIR, OUT_DIR
from pipeline.models import RawPost
from pipeline.sources import devto, hackernews, lemmy, lobsters, reddit, stackexchange
from pipeline.stages import cluster as cluster_stage
from pipeline.stages import dedupe as dedupe_stage
from pipeline.stages import embed as embed_stage
from pipeline.stages import export as export_stage
from pipeline.stages import filter as filter_stage
from pipeline.stages import normalize as normalize_stage
from pipeline.stages import score as score_stage
from pipeline.stages import synthesize as synthesize_stage

log = logging.getLogger("pipeline")

_SINCE_RE = re.compile(r"^(\d+)([dh])$", re.IGNORECASE)


def parse_since(value: str) -> datetime:
    """`'7d'` / `'24h'` / `'90d'` → an aware UTC datetime in the past."""
    m = _SINCE_RE.match(value)
    if not m:
        raise argparse.ArgumentTypeError(
            f"--since must look like '7d' or '24h', got {value!r}"
        )
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
    return datetime.now(tz=UTC) - delta


def _ingest_all(since: datetime) -> Iterator[RawPost]:
    log.info("ingest: fetching posts since %s", since.isoformat())
    yield from reddit.fetch(since)
    yield from hackernews.fetch(since)
    yield from devto.fetch(since)
    yield from lobsters.fetch(since)
    yield from stackexchange.fetch(since)
    yield from lemmy.fetch(since)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smi", description="Social media intel weekly pipeline."
    )
    parser.add_argument("--since", type=parse_since, default=parse_since("7d"))
    parser.add_argument("--out", default=OUT_DIR, help="Output directory.")
    parser.add_argument("--cache", default=CACHE_DIR, help="Cluster-state cache dir.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        stream=sys.stdout,
    )

    out_dir = Path(args.out)
    cache_dir = Path(args.cache)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. Ingest from all sources.
    raw_posts = list(_ingest_all(args.since))
    log.info("ingest: %d raw posts total", len(raw_posts))

    # 2. Normalize.
    normalized = [normalize_stage.normalize(r) for r in raw_posts]
    log.info("normalize: %d normalized posts", len(normalized))

    # 3. Dedupe.
    deduped = list(dedupe_stage.dedupe(normalized))
    log.info("dedupe: %d unique posts", len(deduped))

    # 4. Cheap-pass keyword filter (no embeddings needed yet).
    cheap_kept = [p for p in deduped if filter_stage.cheap_pass(p.text)]
    log.info("filter.cheap: %d posts kept", len(cheap_kept))

    # 5. Embed once; reuse the matrix for the semantic filter and clustering.
    import numpy as np  # lazy import — Step 12 main is the only call site

    embedder = embed_stage.Embedder()
    if cheap_kept:
        cheap_embeddings = embedder([p.text for p in cheap_kept])
        # 6. Semantic filter — reuse the embeddings instead of re-computing.
        semantic = filter_stage.SemanticFilter(embed_fn=embedder)
        keep_mask = semantic.keep_mask(cheap_embeddings)
        kept_posts = [p for p, k in zip(cheap_kept, keep_mask, strict=True) if k]
        keep_indices = [i for i, k in enumerate(keep_mask) if k]
        kept_embeddings = (
            cheap_embeddings[keep_indices]
            if keep_indices
            else np.zeros((0, cheap_embeddings.shape[1]), dtype=cheap_embeddings.dtype)
        )
        log.info("filter.semantic: %d posts kept", len(kept_posts))
    else:
        kept_posts = []
        kept_embeddings = np.zeros((0, 384), dtype=np.float32)

    # 7. Cluster — load prior state, cluster, save back.
    state_path = cache_dir / "cluster_state.parquet"
    prior_state = cluster_stage.load_state(state_path)
    clusters, new_state = cluster_stage.cluster_posts(
        kept_posts, kept_embeddings, prior_state=prior_state
    )
    cluster_stage.save_state(new_state, state_path)
    log.info("cluster: produced %d clusters", len(clusters))

    # 8. Score.
    scored = score_stage.score_clusters(clusters)

    # 9. Synthesize via Claude (env-gated; no-op without ANTHROPIC_API_KEY).
    refined, narrative = synthesize_stage.synthesize(scored)

    # 10. Export.
    paths = export_stage.export(
        refined,
        deduped,
        narrative=narrative,
        out_dir=out_dir,
    )
    log.info(
        "export: wrote %s, %s, %s (run %s)",
        paths.dashboard_json,
        paths.clusters_parquet,
        paths.raw_parquet,
        paths.run_id,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
