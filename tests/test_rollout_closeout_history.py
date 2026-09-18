from scripts.rollout_closeout_history import REQUIRED_DATES, audit_scheduled_runs


def _run(run_id: int, date: str, *, conclusion: str = "success", event: str = "schedule") -> dict[str, object]:
    return {
        "id": run_id,
        "event": event,
        "created_at": f"{date}T04:00:00Z",
        "status": "completed",
        "conclusion": conclusion,
        "html_url": f"https://github.test/actions/runs/{run_id}",
    }


def test_all_required_ist_dates_pass_only_with_successful_scheduled_runs() -> None:
    # 04:00 UTC is 09:30 IST on the same date.
    runs = [_run(index + 1, date) for index, date in enumerate(REQUIRED_DATES)]
    rows, blockers = audit_scheduled_runs(runs)

    assert blockers == []
    assert [row.date for row in rows] == list(REQUIRED_DATES)
    assert all(row.status == "PASS" for row in rows)


def test_missing_or_failed_required_day_blocks_closeout() -> None:
    runs = [_run(index + 1, date) for index, date in enumerate(REQUIRED_DATES[:-1])]
    runs[2] = _run(3, REQUIRED_DATES[2], conclusion="failure")

    rows, blockers = audit_scheduled_runs(runs)

    assert rows[2].status == "BLOCKED"
    assert rows[-1].status == "BLOCKED"
    assert f"{REQUIRED_DATES[2]}: non-success scheduled run (failure)" in blockers
    assert f"{REQUIRED_DATES[-1]}: missing scheduled run" in blockers


def test_non_schedule_events_do_not_satisfy_observation_window() -> None:
    runs = [_run(index + 1, date, event="workflow_dispatch") for index, date in enumerate(REQUIRED_DATES)]
    rows, blockers = audit_scheduled_runs(runs)

    assert all(row.status == "BLOCKED" for row in rows)
    assert len(blockers) == len(REQUIRED_DATES)


def test_ist_calendar_date_is_used_not_raw_utc_date() -> None:
    runs = [
        {
            "id": 1,
            "event": "schedule",
            # 18:45 UTC on Sep 13 is 00:15 IST on Sep 14.
            "created_at": "2026-09-13T18:45:00Z",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.test/actions/runs/1",
        }
    ]
    rows, blockers = audit_scheduled_runs(runs)

    assert rows[0].date == "2026-09-14"
    assert rows[0].status == "PASS"
    assert f"2026-09-14: missing scheduled run" not in blockers
