from pathlib import Path


WORKFLOW = Path('.github/workflows/operational-readiness.yml')


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding='utf-8')


def test_operational_workflow_is_manual_only() -> None:
    text = _workflow_text()
    assert 'workflow_dispatch:' in text
    assert 'schedule:' not in text
    assert 'cron:' not in text


def test_operational_workflow_keeps_trust_disabled() -> None:
    text = _workflow_text()
    assert 'TRUST_PROMOTION_ENABLED: "true"' not in text
    assert text.count('TRUST_PROMOTION_ENABLED: "false"') >= 2


def test_one_shot_requires_exact_confirmation_and_single_item_limit() -> None:
    text = _workflow_text()
    assert 'RUN-ONE-BOUNDED-CYCLE' in text
    assert '--processing-limit 1' in text
    assert '--allow-network' in text
    assert '--allow-write' in text
