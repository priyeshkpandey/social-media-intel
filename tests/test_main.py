"""Unit tests for pipeline.main.

The full orchestrator integration is exercised in CI (it needs the ML stack);
here we just test the pure helpers and that the module imports cleanly.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

import pytest

from pipeline import main as pmain


def test_parse_since_days() -> None:
    now = datetime.now(tz=UTC)
    parsed = pmain.parse_since("7d")
    delta = now - parsed
    # Should be very close to 7 days; allow 5 seconds of test-runtime slack.
    assert timedelta(days=7) - delta < timedelta(seconds=5)


def test_parse_since_hours() -> None:
    now = datetime.now(tz=UTC)
    parsed = pmain.parse_since("24h")
    delta = now - parsed
    assert timedelta(hours=24) - delta < timedelta(seconds=5)


def test_parse_since_case_insensitive() -> None:
    a = pmain.parse_since("3D")
    b = pmain.parse_since("3d")
    # Same delta within a second.
    assert abs((a - b).total_seconds()) < 1


@pytest.mark.parametrize("bad", ["7", "7days", "d7", "7m", "", "100", "abc"])
def test_parse_since_rejects_invalid(bad: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        pmain.parse_since(bad)


def test_main_module_imports() -> None:
    """Regression guard: `python -m pipeline.main --help` must not crash."""
    # Just check that the orchestrator module + every stage it touches imports.
    # Heavy ML stages defer their imports inside helpers; main-time imports must
    # not crash even when those libs are missing.
    assert callable(pmain.main)
    assert callable(pmain.parse_since)
