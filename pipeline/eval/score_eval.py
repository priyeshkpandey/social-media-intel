"""Scoring eval — asserts reasonable buckets on hand-crafted clusters.

These aren't precision/recall numbers; they're sanity checks that the
heuristics put each archetype in the bucket a human reviewer would.

Each archetype is a Cluster shaped to test one dimension at a time, plus
one composite. If any of these flips, either the rubric in `config.py`
or the implementation in `pipeline/stages/score.py` regressed — confirm
the change was intentional before relaxing the assertion.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pipeline.models import Cluster, CostMention, NormalizedPost
from pipeline.stages.score import score_clusters


def _p(
    pid: str,
    text: str,
    role: str | None = "engineer",
    sentiment: float = 0.0,
    cost_mentions: list[CostMention] | None = None,
    day: int = 1,
) -> NormalizedPost:
    return NormalizedPost(
        id=pid,
        source="reddit",
        author_handle=None,
        role=role,
        posted_at=datetime(2026, 5, day, tzinfo=UTC),
        url="https://example.com",
        text=text,
        score=0,
        replies_count=0,
        sentiment=sentiment,
        cost_mentions=cost_mentions or [],
    )


def _c(cid: str, posts: list[NormalizedPost], label: str = "x") -> Cluster:
    first = min(p.posted_at for p in posts)
    last = max(p.posted_at for p in posts)
    return Cluster(
        id=cid,
        label=label,
        centroid=[0.0],
        posts=posts,
        first_seen=first,
        last_seen=last,
    )


# ---------- archetype fixtures ----------


def _high_pay_intent_cluster() -> Cluster:
    return _c(
        "pay-intent",
        [
            _p("a1", "I would pay good money for a tool that fixes flaky tests", role="engineer", sentiment=-0.4, day=1),
            _p("a2", "happy to pay for an LLM that does code review", role="engineer", sentiment=-0.5, day=2),
            _p("a3", "we'd buy this tomorrow if it existed, our SaaS is broken", role="founder", sentiment=-0.6, day=3),
            _p("a4", "take my money — anyone built a script for this?", role="devops", sentiment=-0.3, day=4),
            _p("a5", "pay good money for less Kubernetes pain", role="sre", sentiment=-0.4, day=5),
        ],
    )


def _no_pain_cluster() -> Cluster:
    return _c(
        "no-pain",
        [
            _p("b1", "Just shipped a new feature in our product", sentiment=0.3, day=1),
            _p("b2", "Excited about our new launch this quarter", sentiment=0.5, day=2),
        ],
    )


def _agi_impossible_cluster() -> Cluster:
    return _c(
        "agi",
        [
            _p("c1", "This needs AGI to solve, plus FDA regulatory approval", sentiment=-0.2, day=1),
            _p("c2", "It's basically impossible without consciousness research", sentiment=-0.3, day=2),
        ],
    )


def _vscode_extension_cluster() -> Cluster:
    return _c(
        "vscode-ext",
        [
            _p("d1", "Someone build a vscode extension to lint our CI scripts", role="engineer", sentiment=-0.2, day=1),
            _p("d2", "Chrome plugin idea for managing PR review", role="engineer", sentiment=-0.1, day=2),
            _p("d3", "Tiny CLI tool to do this would be a lifesaver", role="devops", sentiment=-0.3, day=3),
        ],
    )


def _expensive_money_cluster() -> Cluster:
    return _c(
        "infra-cost",
        [
            _p(
                "e1",
                "Our cloud bill jumped to $200k/month and we can't explain why",
                role="engineer",
                sentiment=-0.7,
                cost_mentions=[CostMention(kind="money", raw="$200k/month", value=200_000.0, unit="/month")],
                day=1,
            ),
            _p(
                "e2",
                "Spent 3 weeks debugging the cost — needed a team of 5",
                role="engineer",
                sentiment=-0.6,
                cost_mentions=[
                    CostMention(kind="time", raw="3 weeks", value=3.0, unit="weeks"),
                    CostMention(kind="team", raw="team of 5", value=5.0, unit="people"),
                ],
                day=2,
            ),
        ],
    )


# ---------- assertions ----------


def test_high_pay_intent_drives_opportunity_up() -> None:
    high = _high_pay_intent_cluster()
    flat = _no_pain_cluster()
    scored = {s.cluster.id: s for s in score_clusters([high, flat])}
    assert scored["pay-intent"].opportunity > 50.0
    assert scored["no-pain"].opportunity < 35.0
    assert scored["pay-intent"].opportunity > scored["no-pain"].opportunity + 15.0


def test_agi_cluster_marked_low_feasibility() -> None:
    out = score_clusters([_agi_impossible_cluster()])
    assert out[0].feasibility == "low"
    assert out[0].impl_cost_band in {"$100k-1M", ">$1M"}


def test_vscode_extension_cluster_high_feasibility_small_band() -> None:
    out = score_clusters([_vscode_extension_cluster()])
    sc = out[0]
    assert sc.feasibility == "high"
    assert sc.impl_cost_band == "<$10k"


def test_cost_summary_reflects_evidence() -> None:
    out = score_clusters([_expensive_money_cluster()])
    cost = out[0].cost
    assert cost.money_median_usd == 200_000.0
    assert cost.time_median_days == 21.0  # 3 weeks
    assert cost.team_median_people == 5.0
    assert "200k" in cost.summary


def test_demography_top_role_matches_majority() -> None:
    cluster = _high_pay_intent_cluster()
    out = score_clusters([cluster])
    assert out[0].role_top[0][0] == "engineer"  # 2 engineers beat 1 each of founder/devops/sre


def test_no_data_cluster_handles_gracefully() -> None:
    out = score_clusters([_no_pain_cluster()])
    sc = out[0]
    assert sc.cost.summary == "no cost data"
    assert sc.opportunity >= 0.0
    assert sc.feasibility == "medium"  # no signals → medium default
