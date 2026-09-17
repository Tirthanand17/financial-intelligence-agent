from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.recovery.readiness import build_recovery_readiness_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only, secret-free recovery readiness report."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional local JSON output path. No cloud data is mutated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_recovery_readiness_report()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")

    return 0 if report["safe"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
