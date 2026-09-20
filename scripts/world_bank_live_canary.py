from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.services.world_bank_live_canary import (
    WORLD_BANK_LIVE_CANARY_CONFIRMATION,
    run_world_bank_live_canary,
)
from app.sources.world_bank import WORLD_BANK_INDICATOR_SPECS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one bounded World Bank Indicators live persistence canary. "
            "Do not run before operational rollout closeout and explicit review."
        )
    )
    parser.add_argument(
        "--indicator-code",
        choices=sorted(WORLD_BANK_INDICATOR_SPECS),
        default="NY.GDP.MKTP.KD.ZG",
    )
    parser.add_argument("--recent-observations", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--allow-write", action="store_true")
    parser.add_argument(
        "--confirm",
        default="",
        help=f"must equal {WORLD_BANK_LIVE_CANARY_CONFIRMATION!r}",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = run_world_bank_live_canary(
            indicator_code=args.indicator_code,
            recent_observations=args.recent_observations,
            allow_network=args.allow_network,
            allow_write=args.allow_write,
            confirmation=args.confirm,
        )
    except Exception as exc:
        # Emit only symbolic exception type/message from the canary contract; no
        # credentials, response bodies, request headers, or environment values.
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2

    payload = asdict(result)
    payload["observation_periods"] = list(result.observation_periods)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
