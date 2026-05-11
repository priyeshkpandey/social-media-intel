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

- **Cheap pass:** keyword allow list (`KEYWORD_ALLOW`) and block list (`KEYWORD_BLOCK`, covering recruiting, crypto spam, courses, generic motivational posts). Each keyword is compiled with a trailing `\w{0,4}` inflection allowance, so `engineer` matches `engineers`/`engineering`/`engineered` automatically; stem-changing forms like `estimating` are added to `KEYWORD_ALLOW` explicitly. A post is kept iff it matches an allow term and no block term.
- **Semantic pass:** cosine similarity to `ANCHOR_PAIN_SENTENCES` (20 curated examples spanning engineering / devops / QA / PM / founder / customer pain). A post is kept if its max similarity to any anchor exceeds `SEMANTIC_FILTER_THRESHOLD = 0.45`. The anchor list is the single highest-leverage knob in the system and must be reviewed by the operator before each major change (DECIDE-D).

## Embedding & clustering

Configured in `pipeline/config.py`; behavior implemented in Step 6.

- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU-friendly).
- **Dimensionality reduction:** UMAP to 50 dim with `n_neighbors=15, min_dist=0.0` before clustering.
- **Clustering:** HDBSCAN with `min_cluster_size=5, min_samples=2`, cosine metric.
- **Cross-run stability:** new posts are re-assigned to an existing cluster centroid when cosine similarity > `CENTROID_REASSIGN_THRESHOLD = 0.60`; otherwise HDBSCAN may create a new cluster. Centroids persist in `./.cache/cluster_state.parquet`.

## Scoring rubrics

All six dimensions are computed heuristically in `pipeline/stages/score.py`. The implementation reads its inputs from `pipeline/config.py`.

| Dimension | Rubric |
|---|---|
| **Frequency** | `frequency_per_week = posts_in_cluster / (last_seen − first_seen, in weeks; minimum 1 day)`. `frequency_zscore` is the standard z-score against the batch (`std` clamped to 1e-6). The 12-month rolling view is reconstructed at export by stitching prior dashboard.json releases (Step 9). |
| **Perceived cost** | `CostSummary` with medians per kind: `money_median_usd`, `time_median_days` (hours/weeks/months/years normalized to days), `team_median_people`. Plus a human-readable `summary` string. |
| **Demography** | Top 3 (`role`, `share`) tuples by post count. Roles come from `infer_role` (text mentions override the source's default hint). Posts without a role are counted as `other`. |
| **Monetization opportunity** | Composite 0–100: `40·sigmoid(freq_z) + 30·mean_neg_sentiment + 30·pay_intent_density`. Pay-intent uses `PAY_INTENT_PHRASES`. Negative-sentiment magnitude only counts posts with VADER compound < 0. |
| **Feasibility** | Count keyword hits in `FEASIBILITY_LOW_KEYWORDS` vs `FEASIBILITY_HIGH_KEYWORDS`. More low → `low`; more high → `high`; tied → `medium`. |
| **Implementation cost band** | Scope inferred from `IMPL_COST_SCOPE_KEYWORDS` with **largest-wins priority** (`huge > large > medium > small`). The (feasibility, scope) pair indexes a 4×3 lookup: e.g. `(high, small) → <$10k`, `(medium, medium) → $10-100k`, `(low, large) → >$1M`. |

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
