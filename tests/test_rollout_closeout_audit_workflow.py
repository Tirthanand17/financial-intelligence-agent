from pathlib import Path


WORKFLOW = Path('.github/workflows/rollout-closeout-audit.yml')
SCRIPT = Path('scripts/rollout_closeout_history.py')


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def _script_text() -> str:
    return SCRIPT.read_text(encoding='utf-8')


def test_rollout_closeout_audit_is_manual_only_and_read_only() -> None:
    text = _workflow_text()

    assert 'workflow_dispatch: {}' in text
    assert '\n  schedule:' not in text
    assert '--allow-write' not in text
    assert 'SOURCE_MONITORING_ENABLED: "true"' not in text
    assert 'SOURCE_AUTO_INGEST_ENABLED: "true"' not in text
    assert 'TRUST_PROMOTION_ENABLED: "true"' not in text
    assert 'python scripts/rollout_closeout_history.py' in text


def test_rollout_closeout_requires_all_seven_observation_dates() -> None:
    text = _script_text()

    for date in (
        '2026-09-14',
        '2026-09-15',
        '2026-09-16',
        '2026-09-17',
        '2026-09-18',
        '2026-09-19',
        '2026-09-20',
    ):
        assert f'"{date}"' in text

    assert '"event": "schedule"' in text
    assert 'row.get("conclusion") == "success"' in text
    assert 'missing scheduled run' in text
    assert 'non-success scheduled run' in text
    assert 'FINAL: ROLLOUT-CLOSEOUT-BLOCKED' in text
    assert 'FINAL: ROLLOUT-HISTORY-PASS' in text


def test_rollout_closeout_rechecks_current_fail_closed_readiness() -> None:
    text = _workflow_text()

    assert 'scripts/phase17_production_readiness.py' in text
    assert "grep -q '^FINAL: PASS-READ-ONLY'" in text
    assert 'SOURCE_MONITORING_ENABLED: "false"' in text
    assert 'SOURCE_AUTO_INGEST_ENABLED: "false"' in text
    assert 'TRUST_PROMOTION_ENABLED: "false"' in text
    assert "FINAL: ROLLOUT-CLOSEOUT-READY" in text


def test_rollout_closeout_permissions_are_observation_only() -> None:
    text = _workflow_text()

    assert 'contents: read' in text
    assert 'actions: read' in text
    assert 'contents: write' not in text
    assert 'issues: write' not in text
    assert 'actions: write' not in text
    assert 'GH_TOKEN: ${{ github.token }}' in text
    assert 'GITHUB_TOKEN:' not in text
