from pathlib import Path


WORKFLOW = Path('.github/workflows/operational-scheduled.yml')


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_scheduler_runs_once_daily_at_0930_ist() -> None:
    text = _workflow_text()
    assert "cron: '30 9 * * *'" in text
    assert "timezone: 'Asia/Kolkata'" in text
    assert 'schedule:' in text


def test_scheduler_keeps_trust_disabled_and_bounds_each_source() -> None:
    text = _workflow_text()
    assert 'TRUST_PROMOTION_ENABLED: "true"' not in text
    assert text.count('TRUST_PROMOTION_ENABLED: "false"') >= 3
    assert '--processing-limit 1' in text
    assert 'scripts/world_bank_operational_cycle.py' in text
    assert '--allow-network' in text
    assert '--allow-write' in text


def test_scheduler_uses_only_registered_fixed_monitors() -> None:
    text = _workflow_text()
    for monitor in (
        'rbi-press-releases-rss',
        'sebi-rss',
        'nse-daily-buyback-rss',
        'mospi-latest-releases-api',
        'world-bank-india-gdp-api',
    ):
        assert monitor in text
    assert '${{ inputs.monitor_id }}' not in text


def test_world_bank_runs_after_existing_sources_and_remains_serial() -> None:
    text = _workflow_text()
    generic_loop = 'for monitor in "${monitors[@]}"'
    world_bank_runner = 'python scripts/world_bank_operational_cycle.py'
    assert generic_loop in text
    assert world_bank_runner in text
    assert text.index(world_bank_runner) > text.index(generic_loop)
    assert 'matrix:' not in text


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


def test_failure_alert_is_failure_only_deduplicated_and_secret_minimized() -> None:
    text = _workflow_text()

    assert 'operational-failure-alert:' in text
    assert "needs.scheduled-cycle.result == 'failure'" in text
    assert 'issues: write' in text
    assert "[Operational Alert] Scheduled financial-intelligence cycle failed" in text
    assert 'financial-intelligence-scheduled-failure' in text
    assert 'issues.listForRepo' in text
    assert 'issues.createComment' in text
    assert 'issues.create' in text

    alert_section = text.split('operational-failure-alert:', 1)[1]
    for secret_name in (
        'DATABASE_URL',
        'QDRANT_API_KEY',
        'S3_ACCESS_KEY_ID',
        'S3_SECRET_ACCESS_KEY',
    ):
        assert secret_name not in alert_section


def test_alert_permissions_do_not_expand_scheduled_cycle_permissions() -> None:
    text = _workflow_text()
    scheduled_section = text.split('scheduled-cycle:', 1)[1].split('operational-failure-alert:', 1)[0]
    alert_section = text.split('operational-failure-alert:', 1)[1]

    assert 'contents: read' in scheduled_section
    assert 'issues: write' not in scheduled_section
    assert 'issues: write' in alert_section
