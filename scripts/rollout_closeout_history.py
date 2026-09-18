from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


REQUIRED_DATES = (
    "2026-09-14",
    "2026-09-15",
    "2026-09-16",
    "2026-09-17",
    "2026-09-18",
    "2026-09-19",
    "2026-09-20",
)
IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True, slots=True)
class AuditRow:
    date: str
    status: str
    conclusions: tuple[str, ...]
    runs: tuple[tuple[int, str], ...]


def _ist_date(iso_timestamp: str) -> str:
    value = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("GitHub run timestamp must be timezone-aware")
    return value.astimezone(IST).date().isoformat()


def audit_scheduled_runs(runs: Iterable[dict[str, object]]) -> tuple[list[AuditRow], list[str]]:
    scheduled = [row for row in runs if row.get("event") == "schedule"]
    rows: list[AuditRow] = []
    blockers: list[str] = []

    for required_date in REQUIRED_DATES:
        daily = sorted(
            [
                row
                for row in scheduled
                if isinstance(row.get("created_at"), str)
                and _ist_date(str(row["created_at"])) == required_date
            ],
            key=lambda row: str(row["created_at"]),
        )
        conclusions = tuple(
            str(row.get("conclusion") or row.get("status") or "unknown")
            for row in daily
        )
        run_links = tuple(
            (int(row["id"]), str(row.get("html_url") or ""))
            for row in daily
            if isinstance(row.get("id"), int)
        )
        all_successful = bool(daily) and all(
            row.get("conclusion") == "success" for row in daily
        )
        rows.append(
            AuditRow(
                date=required_date,
                status="PASS" if all_successful else "BLOCKED",
                conclusions=conclusions,
                runs=run_links,
            )
        )
        if not daily:
            blockers.append(f"{required_date}: missing scheduled run")
        elif not all_successful:
            blockers.append(
                f"{required_date}: non-success scheduled run ({', '.join(conclusions)})"
            )

    return rows, blockers


def _validate_runs_payload(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise ValueError("Captured workflow-run payload must be a JSON list")
    if len(payload) > 1000:
        raise ValueError("Captured workflow-run payload exceeds bounded 1000-run audit limit")
    rows: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Captured workflow-run payload contains a non-object item")
        rows.append(item)
    return rows


def _load_runs() -> list[dict[str, object]]:
    if len(sys.argv) == 2:
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        return _validate_runs_payload(payload)
    if len(sys.argv) > 2:
        raise ValueError("Expected at most one captured workflow-runs JSON path")

    raw = os.environ.get("ROLLOUT_RUNS_JSON", "").strip()
    if not raw:
        raise ValueError("ROLLOUT_RUNS_JSON is missing")
    if len(raw.encode("utf-8")) > 1_000_000:
        raise ValueError("Captured workflow-run JSON exceeds 1 MiB safety bound")
    return _validate_runs_payload(json.loads(raw))


def _markdown(rows: list[AuditRow], blockers: list[str]) -> str:
    lines = [
        "## Initial scheduler rollout observation history",
        "",
        "| IST date | Status | Conclusion(s) | Run(s) |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        conclusions = ", ".join(row.conclusions) if row.conclusions else "missing"
        run_links = ", ".join(
            f"[{run_id}]({url})" if url else str(run_id)
            for run_id, url in row.runs
        ) or "-"
        lines.append(f"| {row.date} | {row.status} | {conclusions} | {run_links} |")
    lines.extend(
        [
            "",
            "This audit is read-only and does not change cadence, sources, gates, trust, evidence, or storage.",
            "",
        ]
    )
    if blockers:
        lines.append("**Blockers:**")
        lines.extend(f"- {item}" for item in blockers)
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    try:
        runs = _load_runs()
        rows, blockers = audit_scheduled_runs(runs)
    except Exception as exc:
        print(
            f"BLOCKED: rollout history could not be audited ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2

    summary = _markdown(rows, blockers)
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        Path(summary_path).write_text(summary + "\n", encoding="utf-8")

    if blockers:
        print("FINAL: ROLLOUT-CLOSEOUT-BLOCKED")
        return 1

    print("FINAL: ROLLOUT-HISTORY-PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
