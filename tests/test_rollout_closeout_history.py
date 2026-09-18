from scripts.rollout_closeout_history import REQUIRED_IST_DATES, audit_scheduled_runs


def _run(run_id: int, date: str, *, conclusion: str = "success", event: str = "schedule") -> dict[str, object]:
    return {
        "id": run_id,
        "event": event,
        "created_at": f"{date}T04:00:00Z",
        "status": "completed",
        "conclusion": conclusion,
        "html_url": f"https://github.com/example/repo/actions/runs/{run_id}",
    }


def test_rollout_history_passes_only_when_all_seven_ist_days_succeed() -> None:
    runs = [_run(index, date) for index, date in enumerate(REQUIRED_IST_DATES, start=1)]

    rows, blockers = audit_scheduled_runs(runs)

    assert blockers == []
    assert [row.ist_date for row in rows] == list(REQUIRED_IST_DATES)
    assert {row.status for row in rows} == {"PASS"}


def test_rollout_history_blocks_missing_required_day() -> None:
    runs = [_run(index, date) for index, date in enumerate(REQUIRED_IST_DATES[:-1], start=1)]

    rows, blockers = audit_scheduled_runs(runs)

    assert rows[-1].status == "BLOCKED"
    assert blockers == ["2026-09-20: missing scheduled run"]


def test_rollout_history_blocks_any_non_success_scheduled_attempt() -> None:
    runs = [_run(index, date) for index, date in enumerate(REQUIRED_IST_DATES, start=1)]
    runs.append(_run(99, "2026-09-18", conclusion="failure"))

    rows, blockers = audit_scheduled_runs(runs)

    sep18 = next(row for row in rows if row.ist_date == "2026-09-18")
    assert sep18.status == "BLOCKED"
    assert sep18.conclusions == ("success", "failure")
    assert blockers == ["2026-09-18: non-success scheduled run (success, failure)"]


def test_rollout_history_ignores_manual_runs() -> None:
    runs = [_run(index, date) for index, date in enumerate(REQUIRED_IST_DATES, start=1)]
    runs.append(_run(99, "2026-09-18", conclusion="failure", event="workflow_dispatch"))

    rows, blockers = audit_scheduled_runs(runs)

    assert blockers == []
    sep18 = next(row for row in rows if row.ist_date == "2026-09-18")
    assert sep18.conclusions == ("success",)


def test_rollout_history_groups_by_asia_kolkata_calendar_date() -> None:
    runs = [_run(index, date) for index, date in enumerate(REQUIRED_IST_DATES, start=1)]
    # 2026-09-17 20:00 UTC is already 2026-09-18 in Asia/Kolkata. Replace the
    # normal Sep18 run to prove the audit uses the local calendar date.
    runs = [row for row in runs if row["created_at"] != "2026-09-18T04:00:00Z"]
    runs.append(
        {
            "id": 88,
            "event": "schedule",
            "created_at": "2026-09-17T20:00:00Z",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/example/repo/actions/runs/88",
        }
    )

    rows, blockers = audit_scheduled_runs(runs)

    assert blockers == []
    sep18 = next(row for row in rows if row.ist_date == "2026-09-18")
    assert sep18.run_ids == (88,)
