"""Pipeline configuration: sources, thresholds, and scoring rubrics.

This file is the single source of truth for every tunable knob.
**Whenever you change a value here, update `METHODOLOGY.md` to match.**

DECIDE-C and DECIDE-D from BUILD_PROMPT.md §15 live here — see the
SUBREDDITS and ANCHOR_PAIN_SENTENCES lists. Both must be reviewed by
the operator before the first real run.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# Output / runtime paths
# ---------------------------------------------------------------------------

OUT_DIR: Final[str] = "./out"
CACHE_DIR: Final[str] = "./.cache"
SCHEMA_VERSION: Final[int] = 1
LOOKBACK_WINDOW_MONTHS: Final[int] = 12

# ---------------------------------------------------------------------------
# Roles — canonical taxonomy for the demography dimension.
# ---------------------------------------------------------------------------

ROLES: Final[tuple[str, ...]] = (
    "engineer",
    "manager",
    "product_manager",
    "project_manager",
    "qa",
    "devops",
    "sre",
    "founder",
    "designer",
    "data",
    "security",
    "support",
    "customer",
    "other",
)

# ---------------------------------------------------------------------------
# Sources — DECIDE-C: operator should review this list before first run.
# Each subreddit gets a default role hint applied to its posts.
# ---------------------------------------------------------------------------

SUBREDDITS: Final[dict[str, str]] = {
    "ExperiencedDevs": "engineer",
    "cscareerquestions": "engineer",
    "programming": "engineer",
    "devops": "devops",
    "sre": "sre",
    "QualityAssurance": "qa",
    "softwaretesting": "qa",
    "ProductManagement": "product_manager",
    "projectmanagement": "project_manager",
    "engineeringmanagers": "manager",
    "sysadmin": "devops",
    "SaaS": "founder",
    "startups": "founder",
    "webdev": "engineer",
    "datascience": "data",
    "MachineLearning": "data",
    "netsec": "security",
    "AskNetsec": "security",
}

HN_QUERIES: Final[tuple[str, ...]] = (
    "Ask HN",
    "Show HN",
    "software engineer",
    "devops",
    "on-call",
    "incident",
    "ci pipeline",
    "kubernetes",
)

# Pain-keyword queries used against HN *comments* (Algolia `tags=comment`).
# Comments are where engineers actually vent and quantify cost — much higher
# pain-signal density than stories. "Ask HN" / "Show HN" are dropped here
# (those are title prefixes, not meaningful in comment full-text search).
HN_COMMENT_QUERIES: Final[tuple[str, ...]] = (
    "on-call",
    "burnout",
    "incident",
    "outage",
    "tech debt",
    "legacy",
    "estimate",
    "stakeholder",
    "roadmap",
    "kubernetes",
    "ci pipeline",
    "deadline",
)

STACKEXCHANGE_SITE: Final[str] = "stackoverflow"
STACKEXCHANGE_TAGS: Final[tuple[str, ...]] = (
    "ci-cd",
    "devops",
    "testing",
    "kubernetes",
    "monitoring",
    "code-review",
)

DEVTO_TAGS: Final[tuple[str, ...]] = (
    "devops",
    "testing",
    "career",
    "productivity",
    "management",
    "watercooler",
)

LOBSTERS_RSS: Final[str] = "https://lobste.rs/rss"

# Lemmy is a federated Reddit-clone with a public REST API per instance.
# Each entry is (instance, community, role_hint). No auth required; data-center
# IPs are fine. Curated 2026-05-12 after empirically dropping zero-yield ones:
#   * removed programming.dev/c/devops (dead community)
#   * removed lemmy.world/c/programming (dead — the community isn't federated
#     into lemmy.world's frontend; the real /c/programming lives on
#     programming.dev and lemmy.ml)
#   * moved asklemmy from programming.dev (404) to lemmy.world where it
#     actually exists
#   * added sh.itjust.works/c/programming as a third active instance
LEMMY_COMMUNITIES: Final[tuple[tuple[str, str, str], ...]] = (
    ("programming.dev", "programming", "engineer"),
    ("lemmy.ml", "programming", "engineer"),
    ("lemmy.world", "asklemmy", "engineer"),
    # Removed: sh.itjust.works/c/programming — 0 posts on 2026-05-12, community
    # appears not to exist on that instance.
)

# ---------------------------------------------------------------------------
# Filter — Step 5
# ---------------------------------------------------------------------------

KEYWORD_ALLOW: Final[tuple[str, ...]] = (
    "engineer",
    "developer",
    "devops",
    "sre",
    "qa",
    "tester",
    "pm",
    "product manager",
    "project manager",
    "manager",
    "startup",
    "saas",
    "codebase",
    "ci/cd",
    "pipeline",
    "oncall",
    "on-call",
    "kubernetes",
    "incident",
    "deploy",
    "pull request",
    "code review",
    "tech debt",
    "legacy",
    "stakeholder",
    "outage",
    "burnout",
    "scope creep",
    "estimate",
    "estimating",
    "roadmap",
    "infrastructure",
)

KEYWORD_BLOCK: Final[tuple[str, ...]] = (
    "hiring",
    "we're hiring",
    "join our team",
    "buy now",
    "discount code",
    "crypto",
    "nft",
    "airdrop",
    "shitpost",
    "ama with",
    "free course",
)

SEMANTIC_FILTER_THRESHOLD: Final[float] = 0.40

# DECIDE-D: anchor pain-point sentences for the semantic filter pass.
# The semantic filter keeps posts whose max cosine similarity to any of
# these anchors exceeds SEMANTIC_FILTER_THRESHOLD. These are the highest-
# leverage configuration in the system — review and edit before first run.
#
# 2026-05-12: bumped 20 → 28 anchors. The original 20 produced ~93% drop on
# the first real Reddit-alternative run; eight new anchors cover themes that
# surfaced as live clusters (AI-coding quality, microservices observability,
# deploy reliability) plus adjacent likely-to-appear ones (config sprawl,
# retention, observability cost, DB migration anxiety, AI verification cost).
ANCHOR_PAIN_SENTENCES: Final[tuple[str, ...]] = (
    "On-call rotations are burning out our engineers.",
    "Our CI pipeline takes hours and blocks every pull request.",
    "Flaky tests are eating my week and nobody on the team will fix them.",
    "Cloud infrastructure costs are spiraling and we cannot predict the bill.",
    "We spend more time in meetings and status updates than actually building.",
    "Legacy code is impossible to refactor without breaking production.",
    "We cannot get reliable error tracking across our microservices.",
    "Estimating delivery dates is a constant source of friction with stakeholders.",
    "Our incident response is ad-hoc and we keep hitting the same outages.",
    "Recruiting engineers takes months and most candidates ghost us.",
    "I would pay good money for a tool that writes integration tests automatically.",
    "SOC2 and compliance audits eat weeks of engineering time every year.",
    "Customer onboarding is manual and we lose deals because of it.",
    "Our product roadmap keeps getting overridden by sales escalations.",
    "We cannot tell which features actually drive retention.",
    "Database migrations on a live system terrify the team.",
    "Documentation rots and nobody trusts it after a quarter.",
    "Kubernetes complexity is a tax we pay every single day.",
    "AI coding assistants help but their hallucinations cost us debugging time.",
    "Our QA team cannot keep up with the feature velocity.",
    # Added 2026-05-12 — themes that surfaced as live clusters or were under-represented.
    "Our AI coding assistant generates plausible-looking code that ships bugs we don't catch.",
    "We can't trace a single request through 30 microservices without spending half a day.",
    "Friday deploys are roulette; we've stopped doing them and now work piles up over weekends.",
    "Every new tool we adopt brings config files our team can't fully reason about.",
    "Senior engineers leave faster than we can backfill the institutional knowledge.",
    "Our observability bill exceeds compute spend and still misses real incidents.",
    "Database schema migrations on hot production tables terrify the team.",
    "AI-generated pull requests need so much verification we save almost no engineering time.",
)

# ---------------------------------------------------------------------------
# Cost-mention extraction — Step 5/7
# Each pattern emits a CostMention(kind=..., raw=match, value=..., unit=...).
# ---------------------------------------------------------------------------

MONEY_REGEX: Final[re.Pattern[str]] = re.compile(
    r"\$\s?(?P<value>\d+(?:\.\d+)?)\s?(?P<unit>k|m|million|thousand|/month|/yr|/year)?",
    re.IGNORECASE,
)
TIME_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s+(?P<unit>hour|hours|day|days|week|weeks|month|months|year|years)\b",
    re.IGNORECASE,
)
TEAM_REGEX: Final[re.Pattern[str]] = re.compile(
    r"(?:team of|squad of)\s+(?P<value>\d+)|(?P<value2>\d+)\s+(?:engineers|developers|FTEs|people)",
    re.IGNORECASE,
)

PAY_INTENT_PHRASES: Final[tuple[str, ...]] = (
    "would pay",
    "willing to pay",
    "we pay for",
    "we'd buy",
    "happy to pay",
    "pay good money",
    "take my money",
)

# ---------------------------------------------------------------------------
# Embedding & clustering — Step 6
# ---------------------------------------------------------------------------

EMBEDDING_MODEL: Final[str] = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM: Final[int] = 384  # MiniLM-L6-v2 native dim

UMAP_N_COMPONENTS: Final[int] = 50
UMAP_N_NEIGHBORS: Final[int] = 15
UMAP_MIN_DIST: Final[float] = 0.0

HDBSCAN_MIN_CLUSTER_SIZE: Final[int] = 5
HDBSCAN_MIN_SAMPLES: Final[int] = 2
# "leaf" returns the leaves of the cluster tree → finer-grained clusters.
# Default "eom" (excess of mass) tends to merge sub-themes into mega-clusters
# when one topic dominates the batch (observed 2026-05-12: a single AI-coding
# cluster absorbed 359 of 388 posts). Switching to "leaf" splits dominant
# topics into their natural sub-themes.
HDBSCAN_CLUSTER_SELECTION_METHOD: Final[str] = "leaf"

# Cosine similarity threshold for assigning a new post to an existing
# cluster's centroid (preserves cluster IDs across runs).
CENTROID_REASSIGN_THRESHOLD: Final[float] = 0.60

# ---------------------------------------------------------------------------
# Feasibility classifier — Step 7
# ---------------------------------------------------------------------------

FEASIBILITY_LOW_KEYWORDS: Final[tuple[str, ...]] = (
    "impossible",
    "AGI",
    "physics",
    "regulatory",
    "FDA",
    "consciousness",
)
FEASIBILITY_HIGH_KEYWORDS: Final[tuple[str, ...]] = (
    "LLM",
    "automation",
    "script",
    "saas",
    "tool",
    "extension",
    "plugin",
    "linter",
    "cli",
)

# ---------------------------------------------------------------------------
# Implementation-cost banding — Step 7
# Crude rubric driven by feasibility and scope keywords. Documented in METHODOLOGY.md.
# ---------------------------------------------------------------------------

IMPL_COST_SCOPE_KEYWORDS: Final[dict[str, tuple[str, ...]]] = {
    "small": ("script", "plugin", "extension", "chrome", "vscode", "cli"),
    "medium": ("webapp", "saas", "dashboard", "api", "integration"),
    "large": ("platform", "database", "infrastructure", "kubernetes", "multi-region"),
    "huge": ("operating system", "compiler", "browser", "hardware", "foundation model"),
}

# ---------------------------------------------------------------------------
# Synthesis (Claude) — Step 8
# ---------------------------------------------------------------------------

TOP_N_FOR_SYNTHESIS: Final[int] = 25
SYNTHESIS_BUDGET_USD: Final[float] = 1.00
# Use Anthropic model aliases (no date suffix). Pricing per shared/models.md.
HAIKU_MODEL: Final[str] = "claude-haiku-4-5"
SONNET_MODEL: Final[str] = "claude-sonnet-4-6"

# Per-1M-token pricing in USD (Haiku 4.5 / Sonnet 4.6).
HAIKU_INPUT_PRICE_PER_M: Final[float] = 1.0
HAIKU_OUTPUT_PRICE_PER_M: Final[float] = 5.0
HAIKU_CACHE_WRITE_PRICE_PER_M: Final[float] = 1.25
HAIKU_CACHE_READ_PRICE_PER_M: Final[float] = 0.1
SONNET_INPUT_PRICE_PER_M: Final[float] = 3.0
SONNET_OUTPUT_PRICE_PER_M: Final[float] = 15.0

# ---------------------------------------------------------------------------
# Source rate-limiting & retries
# ---------------------------------------------------------------------------

USER_AGENT: Final[str] = (
    "social-media-intel/0.1 (+https://github.com/priyeshkpandey/social-media-intel)"
)
HTTP_TIMEOUT_SECONDS: Final[int] = 30
HTTP_MAX_RETRIES: Final[int] = 5
HTTP_BACKOFF_BASE_SECONDS: Final[float] = 1.5
