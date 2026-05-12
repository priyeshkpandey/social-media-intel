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
- **Semantic pass:** cosine similarity to `ANCHOR_PAIN_SENTENCES` (28 curated examples spanning engineering / devops / SRE / QA / PM / founder / customer pain, plus AI-coding and observability themes). A post is kept if its max similarity to any anchor exceeds `SEMANTIC_FILTER_THRESHOLD = 0.40`. The anchor list is the single highest-leverage knob in the system and must be reviewed by the operator before each major change (DECIDE-D). The orchestrator computes embeddings once and feeds them to `SemanticFilter.keep_mask()` to avoid re-embedding for clustering downstream.

## Embedding & clustering

Configured in `pipeline/config.py`; behavior implemented in Step 6.

- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2` (384-dim, CPU-friendly).
- **Dimensionality reduction:** UMAP to 50 dim with `n_neighbors=15, min_dist=0.0` before clustering.
- **Clustering:** HDBSCAN with `min_cluster_size=5, min_samples=2`, `cluster_selection_method="leaf"` (chosen 2026-05-12 — the default `"eom"` was merging dominant topics into one mega-cluster on weeks with a strong theme; `"leaf"` returns the leaves of the cluster tree for finer-grained sub-themes).
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

Implemented in `pipeline/stages/synthesize.py`. Env-gated by `ANTHROPIC_API_KEY` — when unset, the stage is a no-op and the dashboard renders heuristic-only output with a banner.

- **Per-cluster (Haiku 4.5):** for the top `TOP_N_FOR_SYNTHESIS = 25` clusters by heuristic `opportunity`, one API call each. System prompt is reused with `cache_control={"type": "ephemeral"}` (cache only activates above Haiku 4.5's 4096-token prefix minimum; harmless when under). Response is structured JSON via `output_config.format` (no markdown-fence parsing). Haiku 4.5 doesn't support `effort` and is called without it. Output is a `ClusterSynthesis` attached to the `ScoredCluster`.
- **Weekly narrative (Sonnet 4.6):** one call against all refined cluster syntheses produces the dashboard hero JSON (`headline`, `top_10`, `honorable_mentions`). Uses adaptive thinking (`thinking={"type": "adaptive"}`) + `effort: "high"`.
- **Budget cap:** `SYNTHESIS_BUDGET_USD = 1.00` per run. After each API call, cost is accumulated from `usage.input_tokens`, `output_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` against per-1M-token prices in `config.py`. Once `spent ≥ budget`, remaining Haiku calls are skipped and the Sonnet call is suppressed.
- **Failure handling:** any per-call exception or malformed JSON drops that cluster back to heuristic-only output (its `synthesis` field stays `None`). The narrative call is suppressed when every cluster fell back.

## Artifacts (Step 9)

Each weekly run emits three files to `./out/`:

- **`dashboard.json`** (≤2MB target) — schema-versioned (`schema_version: 1`) JSON the static site renders directly. Contains: `run_id` (`vYYYY-WW` ISO week), `generated_at`, `heuristic_only` (bool, true when no cluster received LLM refinement), `kpi` (`total_posts_this_week`, `active_clusters`, `new_clusters_this_week` over a 7-day window, `mean_opportunity`), `narrative` (the Sonnet Top-10 object or `null`), and `clusters[]`. Each cluster carries its full scored fields plus up to **10 representative posts** sorted by score, with text truncated to 500 chars + ellipsis. Full text lives in `raw.parquet`.
- **`clusters.parquet`** — one row per cluster with nested fields (`cost`, `role_top`, `synthesis`) serialized to JSON-string columns for compact pyarrow storage.
- **`raw.parquet`** — one row per normalized post. Includes a `cluster_id` column (nullable for posts that were filtered out before clustering) so the artifact is self-joinable.

The 12-month rolling time series is reconstructed at render time by fetching prior GitHub Releases — `dashboard.json` only carries the current run's slice.

## Limitations

These are v1 trade-offs surfaced during the first weeks of live operation. Each is a candidate for a follow-up improvement when the cost/value math justifies it.

### Source coverage

- **X (Twitter) and LinkedIn are deliberately excluded.** Pain points unique to those communities are invisible to this pipeline.
- **Reddit ingest is currently gated.** Reddit ended self-service API-key creation in November 2025 under the "Responsible Builder Policy"; new OAuth applications require manual pre-approval. Until those credentials are granted, `pipeline/sources/reddit.py` runs but yields zero posts (every subreddit fetch 403s from data-center IPs).
- **Reddit-alternative sources are wired up** to recover signal without Reddit:
  - **HN comments** — `tags=comment` against pain-keyword queries (`HN_COMMENT_QUERIES` in `config.py`). Comments are where engineers actually quantify cost ("3 weeks", "$200k/month"), so signal density is higher than stories.
  - **Lemmy** — federated Reddit-clone, public REST API per instance (`LEMMY_COMMUNITIES` in `config.py`). Lower volume than Reddit but dev-focused by construction. No auth required, works from data-center IPs.
- **HN "Show HN" stories** are mostly product launches, not pain. We rely on the semantic filter to drop these; if the filter loosens, HN noise will leak through.

### Filter aggressiveness

- **The semantic filter dropped ~93% of cheap-pass posts** on the first live run (712 → 53). That's the correct behavior for that input mix (heavy on Show-HN/listicles), but it means cluster density is highly sensitive to the anchor-sentence set in `config.py:ANCHOR_PAIN_SENTENCES` and the `SEMANTIC_FILTER_THRESHOLD = 0.45` cutoff. If you change either, expect cluster counts to swing by 5–10×.
- The anchor list is hand-curated and English-only.

### Time-series fidelity

- **`frequency_per_week` and `frequency_zscore` are batch-local** — they describe this week's cluster activity relative to other clusters in this same run, not the historical norm. A cluster's "z-score" is meaningful within a run but not comparable across runs.
- **The dashboard's "activity timeline" plots only the current week's representative posts**, not the 12-month rolling window BUILD_PROMPT.md envisions. Multi-release stitching (fetch the prior N releases' dashboard.json files and concatenate) isn't wired up in v1. Until it lands, the timeline is a single-week density chart.

### LLM cost & failure

- **The `$1.00/run` budget cap is per-run, not per-month.** Worst case at the weekly cadence: 52 × $1 = $52/year. Realistic recent runs cost ~$0.03–0.10. There's no cumulative monthly ceiling — if Anthropic pricing changes or the cluster count spikes (more Haiku calls), the cap won't catch it.
- **Sonnet narrative is best-effort.** When the call fails or returns no text block (e.g., adaptive thinking eats the `max_tokens` budget), the dashboard falls back to the heuristic ranking with no banner — the user sees fewer ranked cards but no error. Diagnostic logging now surfaces the `stop_reason` so failures are debuggable.

### Cluster stability

- **Centroid-based reassignment can drift** when a cluster's underlying topic shifts. If new posts pull the centroid more than `CENTROID_REASSIGN_THRESHOLD = 0.60` away from a prior centroid, a new cluster is spawned and the old one becomes inactive — which can fragment what is intuitively the same pain point over multiple weeks. There's no manual merge UI in v1.
