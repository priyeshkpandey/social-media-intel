# Methodology

> This document describes how the pain-point intelligence is computed. It is the source of truth for every threshold and rubric used in the pipeline. **Update this file whenever `pipeline/config.py` changes.**

## Pipeline overview

```
ingest → normalize → filter → dedupe → embed → cluster → score → synthesize → export
```

Each stage is implemented in `pipeline/stages/`. See [`BUILD_PROMPT.md`](./BUILD_PROMPT.md) for the architectural rationale.

## Sources

See [`pipeline/sources/SOURCES.md`](./pipeline/sources/SOURCES.md) for the active source list and ToS/license posture per source. X (Twitter) and LinkedIn are deliberately excluded — the platform uses developer-community proxies instead.

## Filtering

_To be documented in Step 5._

- **Cheap pass:** keyword allow/block lists.
- **Semantic pass:** cosine similarity to ~20 curated anchor pain-point sentences (DECIDE-D), threshold `0.45`.

## Embedding & clustering

_To be documented in Step 6._

- Embedding model: `sentence-transformers/all-MiniLM-L6-v2`.
- Clustering: HDBSCAN on UMAP-reduced (50-dim) vectors, `min_cluster_size=5, min_samples=2`.
- Stability across runs: posts are re-assigned to existing cluster centroids when cosine similarity > `0.6`.

## Scoring rubrics

_To be documented in Step 7 — final values come from `pipeline/config.py`._

| Dimension | Rubric (placeholder until step 7) |
|---|---|
| Frequency | Posts/week, plus z-score vs all clusters in the 12-month window |
| Perceived cost | Regex-extracted `$N` / `N hours-weeks` / `team of N` mentions, aggregated as medians |
| Demography | Role tally per post (subreddit + text mentions + SO/HN tags) |
| Monetization opportunity | Composite: frequency × negativity × pay-intent phrase presence |
| Feasibility | Keyword bucket → low / medium / high |
| Implementation cost | Coarse band: <$10k / $10–100k / $100k–1M / >$1M |

## Claude synthesis

_To be documented in Step 8._

- Per-cluster (top 25): Haiku 4.5 with prompt-cached system prompt.
- Weekly synthesis: Sonnet 4.6, one call against all 25 Haiku outputs.
- Hard budget: $1.00/run; abort otherwise.
- Heuristic-only fallback when `ANTHROPIC_API_KEY` is unset.

## Limitations

_To be filled in after Step 13._

- Proxy sources are not a 1:1 substitute for X/LinkedIn coverage.
- Free-tier API rate limits constrain weekly volume.
- Cluster stability across weeks is centroid-based and can drift; see Step 6 notes when written.
