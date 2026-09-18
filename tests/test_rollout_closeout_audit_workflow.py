from pathlib import Path


WORKFLOW = Path('.github/workflows/rollout-closeout-audit.yml')


def _text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_rollout_closeout_audit_is_manual_only_and_read_only() -> None:
    text = _text()

    assert 'workflow_dispatch:' in text
    assert '\n  schedule:' not in text
    assert '--allow-write' not in text
    assert 'SOURCE_MONITORING_ENABLED: "true"' not in text
    assert 'SOURCE_AUTO_INGEST_ENABLED: "true"' not in text
    assert 'TRUST_PROMOTION_ENABLED: "true"' not in text


def test_rollout_closeout_delegates_history_validation_to_bounded_script() -> None:
    text = _text()

    assert 'python scripts/rollout_closeout_history.py' in text
    assert 'GITHUB_TOKEN: ${{ github.token }}' in text
    assert 'permissions: read-all' in text


def test_rollout_closeout_rechecks_current_fail_closed_readiness() -> None:
    text = _text()

    assert 'scripts/phase17_production_readiness.py' in text
    assert "grep -q '^FINAL: PASS-READ-ONLY'" in text
    assert 'SOURCE_MONITORING_ENABLED: "false"' in text
    assert 'SOURCE_AUTO_INGEST_ENABLED: "false"' in text
    assert 'TRUST_PROMOTION_ENABLED: "false"' in text
    assert "FINAL: ROLLOUT-CLOSEOUT-READY" in text


def test_rollout_closeout_permissions_are_read_only() -> None:
    text = _text()

    assert 'permissions: read-all' in text
    assert 'contents: write' not in text
    assert 'issues: write' not in text
    assert 'actions: write' not in text
