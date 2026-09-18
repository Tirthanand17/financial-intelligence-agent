from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.recovery.rehearsal import build_recovery_rehearsal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a non-destructive recovery rehearsal manifest from live preserved evidence."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional local JSON output path. No production cloud data is mutated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_recovery_rehearsal()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["rehearsal_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
