# Social Media Intelligence Platform — Build Prompt for Claude

> **How to use this file:** Paste this entire document to Claude (Claude Code or claude.ai) and say "Implement this in the current repository, following the build plan in order. Stop and ask before any decision marked **DECIDE**." Then iterate.

---

## 1. Role & Mission

You are a senior full-stack engineer + data engineer. Your job is to ship a **Software-Industry Pain-Point Intelligence Platform** as a static dashboard hosted on **GitHub Pages**, fed by a **Python data pipeline** that runs on a **weekly GitHub Actions cron**, with refreshed datasets published to **GitHub Releases** and consumed by the dashboard at load time.

The platform exists to help its operator (an expert developer) discover *paid* problems in the software industry by mining public discussion. Output must be opinionated, ranked, and actionable — not a generic word cloud.

## 2. Hard Constraints

1. **Free / open-source first.** Paid tools only where there is no viable free alternative. The only paid dependency permitted by default is the **Anthropic API** (used sparingly — see §6.4), and even that must be optional via env-var gating with a heuristic-only fallback.
2. **Repo-native.** Everything lives in this single repository. No external databases, no managed services, no Vercel/Netlify, no Supabase. Data persistence is **GitHub Releases**; compute is **GitHub Actions**; hosting is **GitHub Pages**.
3. **ToS-clean data sources only.** No scraping of X (Twitter) or LinkedIn. Use only the public/RSS/dataset sources listed in §5. If you want to add a new source, document its ToS posture in `pipeline/sources/SOURCES.md` first.
4. **Weekly cadence, 1-year rolling window.** The pipeline runs once a week, ingests the last 7 days of new content, and the dashboard surfaces a rolling 12-month view.
5. **No secrets in repo.** `ANTHROPIC_API_KEY` and any other tokens live in GitHub Actions secrets only.
6. **Reproducible locally.** `make refresh` (or equivalent) must run the full pipeline end-to-end on a developer laptop given the right env vars.
7. **Small diff per PR.** Build incrementally, not in one mega-commit. Follow the build plan in §13.

## 3. Anti-Goals (do NOT do these)

- Do not scrape X/Twitter or LinkedIn directly (legal & fragility risk).
- Do not introduce a backend server. The dashboard is pure static assets.
- Do not commit large data files (>1MB) to the main branch — those go to Releases.
- Do not add user authentication, comments, or any write-path. This is read-only intelligence.
- Do not build a generic "social listening" tool. Stay laser-focused on software-industry pain points and monetization opportunities.
- Do not add a CMS, blog, or marketing pages.

## 4. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                       GitHub Actions (weekly cron)                    │
│                                                                       │
│  fetch sources  →  normalize  →  filter (software-only)               │
│        ↓                                                              │
│  embed (MiniLM) → cluster (HDBSCAN) → score (heuristics)              │
│        ↓                                                              │
│  pick top-N clusters → Claude synthesis (Haiku tag, Sonnet summary)   │
│        ↓                                                              │
│  emit dashboard.json + clusters.json + raw.parquet                    │
│        ↓                                                              │
│  publish as GitHub Release (tag = YYYY-WW)                            │
└──────────────────────────────────────────────────────────────────────┘
                                  ↓
┌──────────────────────────────────────────────────────────────────────┐
│             GitHub Pages (static site, built with Vite)               │
│                                                                       │
│  On load: fetch latest Release's dashboard.json via GitHub API        │
│  Render: KPI tiles, cluster table, charts (ECharts), drill-down panel │
└──────────────────────────────────────────────────────────────────────┘
```

## 5. Data Sources (decided)

All sources are public RSS / open datasets / documented free APIs. **X (Twitter) and LinkedIn are deliberately excluded** in favor of higher-signal, ToS-clean proxies for software-industry discussion.

| Source | Access | Cadence | Why it's a good proxy |
|---|---|---|---|
| **Reddit** — r/ExperiencedDevs, r/cscareerquestions, r/programming, r/devops, r/QualityAssurance, r/ProductManagement, r/projectmanagement, r/sysadmin, r/SaaS, r/startups, r/webdev | Reddit public JSON API (`old.reddit.com/r/X/new.json`, no auth required for read) | Weekly, last 7 days | Threaded complaints/AMAs/rants are dense with pain points and role context |
| **Hacker News** | Algolia HN Search API (`https://hn.algolia.com/api/v1/search_by_date`) — free, no key | Weekly | High-quality discussion, comments often quantify cost/time/money |
| **dev.to** | Public REST API (`https://dev.to/api/articles`) — free, no key | Weekly | Surfaces tooling friction posts and "I built X to solve Y" announcements |
| **Lobsters** | Public RSS (`https://lobste.rs/rss`) | Weekly | Smaller but high-signal practitioner community |
| **Stack Overflow** | Stack Exchange API (`https://api.stackexchange.com/2.3/questions`) — free tier 10k req/day | Weekly | Tag-filtered questions reveal recurring friction points |
| **Hugging Face datasets** (optional, for backfill only) | `datasets` library | One-time at first run | Seed the 12-month window with `pinkmanlove/twitter-software-engineering` style datasets if you find one with permissive license; otherwise skip. Document license in `SOURCES.md`. |

**Implementation note:** Each source lives in `pipeline/sources/<source>.py` and exports a single `fetch(since: datetime) -> Iterator[RawPost]` function. `RawPost` is a dataclass with: `id, source, author_handle, author_role_hint, posted_at, url, text, score, replies_count, raw`.

## 6. Pipeline Design

### 6.1 Stages

```
ingest → normalize → filter → dedupe → embed → cluster → score → synthesize → export
```

Each stage is a function in `pipeline/stages/`; `pipeline/main.py` orchestrates them. Intermediate artifacts are written to `./.cache/` as Parquet so partial reruns are cheap.

### 6.2 Filtering (must be aggressive)

Drop posts that are not about software-industry work life. A two-pass filter:

1. **Cheap pass (regex + keyword allow/block lists):** allow if post contains any of `[engineer, developer, devops, sre, qa, tester, pm, product manager, project manager, manager, startup, saas, codebase, ci/cd, oncall, kubernetes, ...]` AND does not match block patterns (job ads, recruiting spam, crypto pumps, generic motivational posts).
2. **Semantic pass:** compute cosine similarity of post embedding to a curated set of ~20 "anchor" pain-point sentences (e.g., *"On-call rotations are burning out our SREs"*). Keep posts with max similarity > 0.45.

Tune thresholds against a small labeled sample in `pipeline/eval/filter_eval.py`.

### 6.3 Embedding & Clustering

- **Model:** `sentence-transformers/all-MiniLM-L6-v2` (free, 80MB, runs on CPU in Actions in seconds for ~1k posts).
- **Clustering:** HDBSCAN with `min_cluster_size=5, min_samples=2, metric='cosine'` (via `hdbscan` lib on top of UMAP-reduced 50-dim vectors).
- **Cluster labeling:** initial label = c-TF-IDF top terms (BERTopic-style, but implement minimally without the full BERTopic dep).
- **Persistence:** store cluster centroids across runs in `./.cache/cluster_state.parquet` so cluster IDs are stable week-over-week (assign a new post to an existing cluster if cosine to its centroid > 0.6, else let HDBSCAN create a new one).

### 6.4 Scoring (heuristics, no LLM)

For each cluster, compute the six dashboard dimensions as numbers (0–100 scale where applicable):

| Dimension | Heuristic |
|---|---|
| **Frequency** | Posts/week in this cluster over the last 12 months, plus a normalized z-score vs all clusters |
| **Perceived cost** | Regex-extract `$N`, `N hours/days/weeks/months`, `team of N`, `N% of time` mentions; aggregate medians per cluster |
| **Demography** | Tally per-post `author_role_hint` (inferred from subreddit + post-text role mentions + HN/SO tag); produce top-3 roles + their share |
| **Monetization opportunity** | Composite: (frequency z-score) × (mean post sentiment negativity from VADER) × (presence of "I would pay" / "willing to pay" / "we pay for" phrases) |
| **Feasibility** | Cheap classifier over keywords: presence of `["impossible", "AGI", "physics", "regulatory"]` lowers it; presence of `["LLM", "automation", "script", "saas", "tool"]` raises it. Bucket to: low / medium / high |
| **Implementation cost estimate** | Coarse bucket from feasibility + estimated scope keywords: <$10k / $10–100k / $100k–1M / >$1M. Document the rubric in `pipeline/stages/score.py` |

These are intentionally crude. The Claude pass (next) refines the top clusters only.

### 6.5 Synthesis (Claude — top-N only)

For the top 25 clusters by `monetization_opportunity` score:

- **Haiku 4.5** (`claude-haiku-4-5-20251001`): per-cluster, given 10 representative posts + heuristic scores, output a strict-JSON object with refined `{title, one_line_pain, role_demographics, perceived_cost_summary, feasibility, implementation_cost_band, opportunity_pitch, confidence}`. Use prompt caching on the system prompt across all 25 calls (it's the same).
- **Sonnet 4.6** (`claude-sonnet-4-6`): one final synthesis call producing the **"Top 10 Opportunities This Week"** narrative for the dashboard hero section, given all 25 Haiku outputs.

Gating: if `ANTHROPIC_API_KEY` is not set, skip §6.5 entirely; the dashboard falls back to heuristic-only output and shows a banner saying so.

**Budget cap:** abort the synthesis pass if estimated cost > $1.00 per run. Log token usage every call.

### 6.6 Export

Emit three artifacts per run to `./out/`:

- `dashboard.json` (≤2MB): everything the dashboard needs to render — KPI tiles, cluster summaries, time series, top-10 narrative. Versioned schema (`"schema_version": 1`).
- `clusters.parquet` (≤20MB): full cluster data with all posts, for power-user drilldown via a "Download data" button.
- `raw.parquet` (uncapped, can be ~100MB): the week's raw normalized posts. Useful for debugging and for the next run's dedupe.

## 7. Frontend / Dashboard

### 7.1 Stack (decided)

- **Vite** + **TypeScript** (no React/Vue — keep deps minimal; use vanilla TS modules).
- **Apache ECharts** for all charts (free, handles big datasets, has a treemap that fits our cluster view).
- **Pico.css** for baseline styling (free, classless, small). Override sparingly in `site/src/styles.css`.
- No router — single page, sections scrolled or tab-switched via vanilla TS.
- Build output goes to `site/dist/` and is published to GitHub Pages via the official `actions/deploy-pages` workflow.

### 7.2 Sections (in order on the page)

1. **Header** — title, last-refreshed timestamp, "Data source: GitHub Release `vYYYY-WW`" link, banner if running in heuristic-only mode.
2. **Top 10 Opportunities This Week** (hero) — ranked cards, each with: title, one-line pain, opportunity pitch (Sonnet-generated), badges for role + feasibility + cost band. Click → opens drilldown panel.
3. **KPI strip** — 4 tiles: total posts this week, active clusters (12mo), new clusters this week, mean opportunity score trend (sparkline).
4. **Pain-Point Treemap** — ECharts treemap. Size = frequency, color = opportunity score. Hover → cluster summary.
5. **Frequency Over Time** — ECharts stacked area chart, top 15 clusters across the 12-month window.
6. **Demography Heatmap** — clusters (rows) × roles (cols), cell intensity = share of posts. Helps spot "this pain is mostly felt by PMs vs ICs."
7. **Cluster Explorer table** — sortable/filterable. Columns: cluster title, freq, cost, top role, opp score, feasibility, impl cost. Click row → drilldown.
8. **Drilldown panel** — appears on selection: cluster description, top 10 representative posts (with source link), all six scored dimensions with their evidence (quoted snippets that drove the score).
9. **Footer** — methodology link (in-repo `METHODOLOGY.md`), GitHub repo link, "Built with Claude" attribution.

### 7.3 Data loading

On page load:
1. `GET https://api.github.com/repos/{owner}/{repo}/releases/latest` → grab the `dashboard.json` asset URL.
2. Fetch + render. Cache in `localStorage` keyed by release `tag_name` for instant subsequent loads.
3. Show a "stale data" warning if `published_at > 10 days ago` (means the cron failed).

## 8. Storage Strategy — GitHub Releases

- **Tag scheme:** `vYYYY-WW` (e.g., `v2026-19` for ISO week 19 of 2026). One release per pipeline run.
- **Assets per release:**
  - `dashboard.json`
  - `clusters.parquet`
  - `raw.parquet`
  - `run_log.txt` (full pipeline log for debugging)
- **Release notes (auto-generated):** counts, top 10 opportunities summary, link to previous release for diff.
- **Retention:** keep last 60 releases (~14 months). The cleanup is a step at the end of the workflow.

## 9. GitHub Actions Workflows

Two workflows:

### 9.1 `.github/workflows/refresh.yml`

- Trigger: `schedule: cron: '0 6 * * MON'` (Mondays 06:00 UTC) **and** `workflow_dispatch`.
- Concurrency group: `refresh` (skip if already running).
- Steps:
  1. `actions/checkout`
  2. `astral-sh/setup-uv` + `uv sync`
  3. Restore `./.cache/` from `actions/cache` keyed on `cluster_state.parquet` hash (fallback: empty).
  4. Run `uv run python -m pipeline.main --since 7d` (with `ANTHROPIC_API_KEY` from secrets, optional).
  5. Save `./.cache/` back to actions cache.
  6. Create GitHub Release with the three artifacts via `softprops/action-gh-release`.
  7. Trigger the Pages deploy workflow.
  8. Prune releases older than the most recent 60.
- Timeout: 30 minutes.
- On failure: open a GitHub Issue with the log tail (use `actions/github-script`).

### 9.2 `.github/workflows/deploy.yml`

- Trigger: `workflow_run` of refresh.yml on success, plus `push` to `main` paths `site/**`, plus `workflow_dispatch`.
- Steps: checkout → setup-node → `npm ci` in `site/` → `npm run build` → `actions/upload-pages-artifact` → `actions/deploy-pages`.

## 10. Repository Layout

Create exactly this structure. Keep file count low.

```
/
├── BUILD_PROMPT.md              ← this file (already created)
├── README.md                    ← short: what it is, link to live site, link to METHODOLOGY.md
├── METHODOLOGY.md               ← how clusters/scores are computed; rubrics; limitations
├── CLAUDE.md                    ← repo-specific guidance for future Claude sessions
├── LICENSE                      ← MIT
├── pyproject.toml               ← uv-managed Python project
├── uv.lock
├── Makefile                     ← `make refresh`, `make site-dev`, `make site-build`, `make eval`
├── pipeline/
│   ├── __init__.py
│   ├── main.py                  ← CLI orchestrator
│   ├── config.py                ← thresholds, source list, score rubrics
│   ├── models.py                ← dataclasses: RawPost, Cluster, ScoredCluster
│   ├── sources/
│   │   ├── SOURCES.md           ← ToS/license posture per source
│   │   ├── reddit.py
│   │   ├── hackernews.py
│   │   ├── devto.py
│   │   ├── lobsters.py
│   │   └── stackexchange.py
│   ├── stages/
│   │   ├── normalize.py
│   │   ├── filter.py
│   │   ├── dedupe.py
│   │   ├── embed.py
│   │   ├── cluster.py
│   │   ├── score.py
│   │   ├── synthesize.py        ← Claude calls (Haiku + Sonnet); env-gated
│   │   └── export.py
│   ├── eval/
│   │   ├── filter_eval.py
│   │   ├── cluster_eval.py
│   │   └── fixtures/            ← small JSON fixtures, hand-labeled
│   └── prompts/
│       ├── cluster_tag.haiku.md
│       └── weekly_synthesis.sonnet.md
├── site/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── public/
│   │   └── favicon.svg
│   └── src/
│       ├── main.ts
│       ├── data.ts              ← fetch latest release + cache
│       ├── render/
│       │   ├── hero.ts
│       │   ├── kpi.ts
│       │   ├── treemap.ts
│       │   ├── timeseries.ts
│       │   ├── heatmap.ts
│       │   ├── table.ts
│       │   └── drilldown.ts
│       └── styles.css
├── .github/
│   └── workflows/
│       ├── refresh.yml
│       └── deploy.yml
└── .gitignore
```

## 11. Local Development

- `make refresh` — runs the full pipeline; uses `.env` for `ANTHROPIC_API_KEY` (optional). Writes to `./out/`.
- `make site-dev` — runs Vite dev server pointing at `./out/dashboard.json` instead of a Release (via env var).
- `make site-build` — production build to `site/dist/`.
- `make eval` — runs the filter/cluster eval fixtures and prints precision/recall.
- `make lint` — `ruff check` + `tsc --noEmit`.

## 12. Cost Model (target)

- **GitHub Actions:** ~10 min/week × 4 = 40 min/month. Free tier = 2000 min/month → safe.
- **GitHub Pages:** free.
- **GitHub Releases storage:** ~100MB/release × 60 releases = ~6GB. Within free limits.
- **Anthropic API (optional):** Haiku 4.5 ~$1/M input, $5/M output. 25 clusters × ~5k input + 1k output tokens ≈ $0.13 + $0.13 = ~$0.26/week. Sonnet synthesis: ~10k input, 2k output × $3/$15 = ~$0.06. **Total ~$0.32/week ≈ $17/year** if enabled. Hard-cap to $1/run.
- **Everything else:** $0.

## 13. Build Plan (do in order; one PR per step)

> Stop after each step, run tests/lint, commit, and confirm with the user before moving to the next. Steps marked **DECIDE** require user input.

1. **Scaffold the repo:** Layout from §10 with empty stubs, `pyproject.toml`, `Makefile`, `.gitignore`, `LICENSE`, `README.md`, `CLAUDE.md`, `METHODOLOGY.md` skeleton.
2. **Models & config:** `pipeline/models.py`, `pipeline/config.py` with the source list and thresholds.
3. **Sources:** implement `reddit.py` and `hackernews.py` first (highest signal); commit with unit tests that hit a recorded fixture, not the live API.
4. **Sources continued:** `devto.py`, `lobsters.py`, `stackexchange.py`.
5. **Normalize + filter + dedupe:** with a small labeled fixture in `pipeline/eval/fixtures/`.
6. **Embed + cluster:** including persisted cluster state.
7. **Score:** all six heuristic dimensions, with a `score_eval.py` that asserts reasonable buckets on the fixture.
8. **Synthesize:** Haiku + Sonnet calls, env-gated, with prompt caching. Mock the API in tests.
9. **Export:** the three output files with schema versioning.
10. **Frontend scaffold:** Vite + TS + ECharts; render hero + KPI from a checked-in sample `dashboard.json`.
11. **Frontend continued:** treemap, timeseries, heatmap, table, drilldown.
12. **Workflows:** `refresh.yml` and `deploy.yml`. First runs must be `workflow_dispatch` to debug before the cron kicks in.
13. **First real run:** trigger manually, verify the Release, verify Pages renders, fix issues.
14. **DECIDE:** turn on the cron, write a short note in `METHODOLOGY.md` about known limitations.

## 14. Quality Bar

- **Type hints everywhere** in Python (`from __future__ import annotations`; mypy or pyright clean on `--strict` where reasonable).
- **TypeScript strict mode** in the site.
- **Ruff** for Python formatting + lint; no warnings.
- **Tests:** pipeline stages have unit tests against fixtures. The site has at minimum a smoke test that `dashboard.json` of the bundled sample renders without console errors (Playwright optional, not required for v1).
- **Logs:** the pipeline emits structured logs (one JSON per line) to stdout. The `run_log.txt` release asset is that stdout captured.
- **Error handling at boundaries only:** sources retry on 429/5xx with backoff. Internal stages assume valid input.
- **Performance:** full weekly run should fit in <15 min on a GitHub-hosted runner.

## 15. Open Decisions (ask the user)

Even with the answers locked in above, these will come up during the build — flag and ask:

- **DECIDE-A:** Should the dashboard be public (anyone with the Pages URL can view) or behind a GitHub-private-pages setup? *Default: public, since the data is already public.*
- **DECIDE-B:** Brand / repo name in the UI header? *Default: "Software Pain-Point Intel".*
- **DECIDE-C:** Reddit subreddits list — the §5 list is a starting set. Add/remove based on operator's intuition before first run.
- **DECIDE-D:** Anchor pain-point sentences for the semantic filter (~20 examples). Need the operator to curate these — they are the highest-leverage configuration in the whole system. Draft a starter list in `pipeline/config.py` and ask for review before step 5.
- **DECIDE-E:** Are there specific software-industry niches the operator cares about more (e.g., devtools, fintech eng, ML infra)? If so, add per-niche subreddits and bias the filter.

## 16. Done Definition

v1 ships when **all** of:

- [ ] `make refresh` runs end-to-end locally in <15 min and emits the three artifacts.
- [ ] `make site-dev` shows a usable dashboard against the locally-emitted `dashboard.json`.
- [ ] One real GitHub Actions run has published a Release with valid assets.
- [ ] GitHub Pages renders the dashboard against that Release.
- [ ] Heuristic-only mode (no `ANTHROPIC_API_KEY`) works end-to-end with a visible banner.
- [ ] `METHODOLOGY.md` accurately describes every rubric and threshold in `config.py`.
- [ ] Cron is enabled and the next scheduled run is visible in the Actions tab.

---

**Now begin with §13 step 1. Do not skip ahead. Ask before any DECIDE.**
