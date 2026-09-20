from pathlib import Path


WORKFLOW = Path('.github/workflows/world-bank-live-canary-once.yml')


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_world_bank_canary_workflow_is_comment_triggered_and_one_shot_gated() -> None:
    text = _workflow_text()
    assert 'issue_comment:' in text
    assert 'types: [created]' in text
    assert 'schedule:' not in text
    assert 'cron:' not in text
    assert 'workflow_dispatch:' not in text
    assert 'github.event.issue.number == 68' in text
    assert "github.event.comment.user.login == 'Tirthanand17'" in text
    assert "github.event.comment.body == '/run-world-bank-live-canary-2026-09-20'" in text


def test_world_bank_canary_workflow_has_minimal_permissions_and_serial_execution() -> None:
    text = _workflow_text()
    assert 'contents: read' in text
    assert 'contents: write' not in text
    assert 'issues: write' not in text
    assert 'actions: write' not in text
    assert 'cancel-in-progress: false' in text
    assert 'matrix:' not in text


def test_world_bank_canary_workflow_keeps_all_global_gates_false() -> None:
    text = _workflow_text()
    assert 'SOURCE_MONITORING_ENABLED: "false"' in text
    assert 'SOURCE_AUTO_INGEST_ENABLED: "false"' in text
    assert 'TRUST_PROMOTION_ENABLED: "false"' in text
    assert 'TRUST_PROMOTION_ENABLED: "true"' not in text


def test_world_bank_canary_workflow_requires_rollout_and_readiness_before_write() -> None:
    text = _workflow_text()
    canary_index = text.index('Run exactly one bounded World Bank canary')
    assert text.index('Require recorded rollout closeout') < canary_index
    assert text.index('Fail-closed pre-canary readiness') < canary_index
    assert text.index('Fail-closed post-canary readiness') > canary_index
    assert text.count("grep -q '^FINAL: PASS-READ-ONLY'") == 2
    assert 'FINAL: ROLLOUT-CLOSEOUT-READY' in text


def test_world_bank_canary_workflow_is_fixed_bounded_and_explicitly_confirmed() -> None:
    text = _workflow_text()
    assert '--indicator-code NY.GDP.MKTP.KD.ZG' in text
    assert '--recent-observations 3' in text
    assert '--allow-network' in text
    assert '--allow-write' in text
    assert '--confirm WORLD_BANK_LIVE_CANARY' in text
    assert "result.get('claim_count') != 0" in text
    assert "result.get('status') not in {'indexed', 'already_indexed'}" in text
    assert '1 <= chunk_count <= 3' in text


def test_world_bank_canary_workflow_does_not_activate_sources_or_reuse_monitor_cycle() -> None:
    text = _workflow_text()
    assert 'phase14_integrated_cycle_canary.py' not in text
    assert '--processing-limit' not in text
    for monitor in (
        'rbi-press-releases-rss',
        'sebi-rss',
        'nse-daily-buyback-rss',
        'mospi-latest-releases-api',
    ):
        assert monitor not in text
