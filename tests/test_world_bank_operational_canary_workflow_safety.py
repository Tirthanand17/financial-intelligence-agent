from pathlib import Path


WORKFLOW = Path('.github/workflows/world-bank-operational-canary-once.yml')


def _text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_operational_canary_is_exact_owner_comment_trigger_only() -> None:
    text = _text()
    assert 'issue_comment:' in text
    assert 'types: [created]' in text
    assert 'schedule:' not in text
    assert 'cron:' not in text
    assert 'workflow_dispatch:' not in text
    assert 'github.event.issue.number == 70' in text
    assert "github.event.comment.user.login == 'Tirthanand17'" in text
    assert "github.event.comment.body == '/run-world-bank-operational-canary-2026-09-20'" in text


def test_operational_canary_keeps_repository_permissions_read_only() -> None:
    text = _text()
    assert 'contents: read' in text
    assert 'contents: write' not in text
    assert 'issues: write' not in text
    assert 'actions: write' not in text
    assert 'cancel-in-progress: false' in text


def test_operational_canary_has_readiness_before_and_after_live_cycle() -> None:
    text = _text()
    cycle = text.index('Run one bounded World Bank operational monitor canary')
    assert text.index('Fail-closed pre-canary production readiness') < cycle
    assert text.index('Fail-closed post-canary production readiness') > cycle
    assert text.count("grep -q '^FINAL: PASS-READ-ONLY'") == 2


def test_operational_canary_uses_normal_monitoring_gates_but_never_trust_promotion() -> None:
    text = _text()
    assert 'SOURCE_MONITORING_ENABLED: "true"' in text
    assert 'SOURCE_AUTO_INGEST_ENABLED: "true"' in text
    assert 'TRUST_PROMOTION_ENABLED: "true"' not in text
    assert text.count('TRUST_PROMOTION_ENABLED: "false"') >= 3


def test_operational_canary_requires_explicit_write_and_exact_confirmation() -> None:
    text = _text()
    assert 'scripts/world_bank_operational_canary.py' in text
    assert '--allow-network' in text
    assert '--allow-write' in text
    assert '--confirm WORLD_BANK_OPERATIONAL_CANARY' in text
    assert "result.get('claim_count') != 0" in text
    assert "result.get('status') not in {'indexed', 'already_indexed'}" in text


def test_operational_canary_does_not_change_scheduler_or_existing_source_cycles() -> None:
    text = _text()
    assert 'phase14_integrated_cycle_canary.py' not in text
    for monitor in (
        'rbi-press-releases-rss',
        'sebi-rss',
        'nse-daily-buyback-rss',
        'mospi-latest-releases-api',
    ):
        assert monitor not in text
