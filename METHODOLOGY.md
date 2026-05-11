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

Configured in `pipeline/config.py`; behavior implemented in Step 5.

- **Cheap pass:** keyword allow list (`KEYWORD_ALLOW`, 28 terms) and block list (`KEYWORD_BLOCK`, 10 patterns covering recruiting, crypto spam, courses).
- **Semantic pass:** cosine similarity to `ANCHOR_PAIN_SENTENCES` (20 curated examples spanning engineering / devops / QA / PM / founder / customer pain). A post is kept if its max similarity to any anchor exceeds `SEMANTIC_FILTER_THRESHOLD = 0.45`. The anchor list is the single highest-leverage knob in the system and must be reviewed by the operator before each major change (DECIDE-D).

## Embedding & clustering

Configured in `pipeline/config.py`; behavior implemented in Step 6.

- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU-friendly).
- **Dimensionality reduction:** UMAP to 50 dim with `n_neighbors=15, min_dist=0.0` before clustering.
- **Clustering:** HDBSCAN with `min_cluster_size=5, min_samples=2`, cosine metric.
- **Cross-run stability:** new posts are re-assigned to an existing cluster centroid when cosine similarity > `CENTROID_REASSIGN_THRESHOLD = 0.60`; otherwise HDBSCAN may create a new cluster. Centroids persist in `./.cache/cluster_state.parquet`.

## Scoring rubrics

All six dimensions are computed heuristically in Step 7 (`pipeline/stages/score.py`). The implementation reads its inputs from `pipeline/config.py`.

| Dimension | Rubric |
|---|---|
| **Frequency** | `frequency_per_week` (posts/week in the 12-month window) and `frequency_zscore` (z-score vs all clusters) |
| **Perceived cost** | Aggregates `CostMention` rows extracted via `MONEY_REGEX`, `TIME_REGEX`, `TEAM_REGEX`. Reported as a human-readable summary plus medians per kind |
| **Demography** | Top 3 roles by share, derived from `SUBREDDIT_ROLE_HINTS`, post-text role mentions, and SO/HN tags. Canonical taxonomy in `ROLES` |
| **Monetization opportunity** | Composite (0–100): `frequency_zscore × mean_negative_sentiment × pay_intent_phrase_density`, normalized across clusters. Pay-intent phrases listed in `PAY_INTENT_PHRASES` |
| **Feasibility** | `FEASIBILITY_LOW_KEYWORDS` push toward `low`, `FEASIBILITY_HIGH_KEYWORDS` toward `high`, otherwise `medium` |
| **Implementation cost band** | Function of feasibility × scope keywords (`IMPL_COST_SCOPE_KEYWORDS`): `<$10k` / `$10-100k` / `$100k-1M` / `>$1M` |

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
