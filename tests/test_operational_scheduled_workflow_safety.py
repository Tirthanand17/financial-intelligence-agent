from pathlib import Path


WORKFLOW = Path('.github/workflows/operational-scheduled.yml')


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_scheduler_runs_once_daily_at_0930_ist() -> None:
    text = _workflow_text()
    assert "cron: '0 4 * * *'" in text
    assert 'schedule:' in text


def test_scheduler_keeps_trust_disabled_and_bounds_each_source() -> None:
    text = _workflow_text()
    assert 'TRUST_PROMOTION_ENABLED: "true"' not in text
    assert text.count('TRUST_PROMOTION_ENABLED: "false"') >= 3
    assert '--processing-limit 1' in text


def test_scheduler_uses_only_registered_fixed_monitors() -> None:
    text = _workflow_text()
    for monitor in (
        'rbi-press-releases-rss',
        'sebi-rss',
        'nse-daily-buyback-rss',
        'mospi-latest-releases-api',
    ):
        assert monitor in text
    assert '${{ inputs.monitor_id }}' not in text


def test_scheduler_runs_readiness_before_and_after_writes() -> None:
    text = _workflow_text()
    assert 'Fail-closed pre-run readiness' in text
    assert 'Fail-closed post-run readiness' in text
    assert text.count("grep -q '^FINAL: PASS-READ-ONLY'") == 2


def test_scheduler_is_serial_and_non_cancelling() -> None:
    text = _workflow_text()
    assert 'cancel-in-progress: false' in text
    assert 'matrix:' not in text
    assert 'for monitor in "${monitors[@]}"' in text
