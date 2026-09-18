from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


REQUIRED_IST_DATES: tuple[str, ...] = (
    "2026-09-14",
    "2026-09-15",
    "2026-09-16",
    "2026-09-17",
    "2026-09-18",
    "2026-09-19",
    "2026-09-20",
)
IST = ZoneInfo("Asia/Kolkata")
WORKFLOW_FILE = "operational-scheduled.yml"


@dataclass(frozen=True, slots=True)
class DailyAudit:
    ist_date: str
    status: str
    conclusions: tuple[str, ...]
    run_ids: tuple[int, ...]
    run_urls: tuple[str, ...]


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ist_date(value: str) -> str:
    return _parse_datetime(value).astimezone(IST).date().isoformat()


def audit_scheduled_runs(
    runs: Iterable[dict[str, object]],
    *,
    required_dates: tuple[str, ...] = REQUIRED_IST_DATES,
) -> tuple[list[DailyAudit], list[str]]:
    """Audit one successful scheduled workflow run for every required IST day.

    Manual runs are ignored even if supplied accidentally. A day is considered
    safe only when at least one `schedule` event exists and every scheduled run
    found for that IST date concluded successfully. This intentionally treats
    duplicate/non-success scheduled attempts as a closeout blocker for review.
    """
    scheduled = [row for row in runs if row.get("event") == "schedule"]
    rows: list[DailyAudit] = []
    blockers: list[str] = []

    for required_date in required_dates:
        daily = sorted(
            (
                row
                for row in scheduled
                if isinstance(row.get("created_at"), str)
                and _ist_date(str(row["created_at"])) == required_date
            ),
            key=lambda row: str(row.get("created_at", "")),
        )
        conclusions = tuple(str(row.get("conclusion") or row.get("status") or "unknown") for row in daily)
        run_ids = tuple(int(row["id"]) for row in daily if isinstance(row.get("id"), int))
        run_urls = tuple(str(row.get("html_url") or "") for row in daily)
        passed = bool(daily) and all(row.get("conclusion") == "success" for row in daily)

        rows.append(
            DailyAudit(
                ist_date=required_date,
                status="PASS" if passed else "BLOCKED",
                conclusions=conclusions,
                run_ids=run_ids,
                run_urls=run_urls,
            )
        )

        if not daily:
            blockers.append(f"{required_date}: missing scheduled run")
        elif not passed:
            blockers.append(
                f"{required_date}: non-success scheduled run ({', '.join(conclusions)})"
            )

    return rows, blockers


def _fetch_page(url: str, *, token: str) -> dict[str, object]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "financial-intelligence-rollout-closeout-audit",
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API base from Actions context
        return json.loads(response.read().decode("utf-8"))


def fetch_scheduled_workflow_runs(
    *,
    api_url: str,
    repository: str,
    token: str,
    workflow_file: str = WORKFLOW_FILE,
) -> list[dict[str, object]]:
    """Fetch bounded scheduled-run metadata from the current private repository."""
    if api_url.rstrip("/") != "https://api.github.com":
        raise ValueError("Unexpected GitHub API base URL")
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        raise ValueError("Invalid GITHUB_REPOSITORY")
    if not token:
        raise ValueError("GITHUB_TOKEN is required")
    if workflow_file != WORKFLOW_FILE:
        raise ValueError("Unexpected workflow file")

    owner, repo = repository.split("/", 1)
    endpoint = (
        f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        f"/actions/workflows/{quote(workflow_file, safe='')}/runs?"
        + urlencode({"event": "schedule", "per_page": 100})
    )
    payload = _fetch_page(endpoint, token=token)
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("GitHub workflow-runs response is missing workflow_runs")
    return [row for row in runs if isinstance(row, dict)]


def _markdown(rows: list[DailyAudit], blockers: list[str]) -> str:
    lines = [
        "## Initial scheduler rollout observation history",
        "",
        "| IST date | Status | Conclusion(s) | Scheduled run(s) |",
        "|---|---|---|---|",
    ]
    for row in rows:
        conclusions = ", ".join(row.conclusions) or "missing"
        links = ", ".join(
            f"[{run_id}]({url})" if url else str(run_id)
            for run_id, url in zip(row.run_ids, row.run_urls, strict=False)
        ) or "-"
        lines.append(f"| {row.ist_date} | {row.status} | {conclusions} | {links} |")
    lines.extend(
        [
            "",
            "This audit is read-only and does not change cadence, sources, gates, trust, evidence, or storage.",
        ]
    )
    if blockers:
        lines.extend(["", "### Blockers", *[f"- {item}" for item in blockers]])
    return "\n".join(lines) + "\n"


def main() -> int:
    token = os.getenv("GITHUB_TOKEN", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    api_url = os.getenv("GITHUB_API_URL", "https://api.github.com")

    try:
        runs = fetch_scheduled_workflow_runs(
            api_url=api_url,
            repository=repository,
            token=token,
        )
        rows, blockers = audit_scheduled_runs(runs)
    except Exception as exc:
        print(f"ROLLOUT-HISTORY-BLOCKED: {type(exc).__name__}")
        return 2

    summary = _markdown(rows, blockers)
    print(summary, end="")
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(summary, encoding="utf-8")

    if blockers:
        print("FINAL: ROLLOUT-HISTORY-BLOCKED")
        return 2

    print("FINAL: ROLLOUT-HISTORY-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
