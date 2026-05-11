"""Pipeline CLI orchestrator.

Stub for Step 1. Real implementation lands incrementally across Steps 2–9.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="smi", description="Social media intel pipeline.")
    parser.add_argument(
        "--since",
        default="7d",
        help="Lookback window (e.g. '7d', '24h'). Defaults to 7d.",
    )
    parser.add_argument(
        "--out",
        default="./out",
        help="Output directory for dashboard.json / clusters.parquet / raw.parquet.",
    )
    args = parser.parse_args(argv)

    # Stub: real stages wired up in later steps.
    print(f"[smi] stub run; since={args.since} out={args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
