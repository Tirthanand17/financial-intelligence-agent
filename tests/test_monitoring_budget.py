import pytest

from app.monitoring.budget import assess_usage_budget
from app.monitoring.models import CapacityState


def test_unconfigured_budget_is_unknown_not_assumed_safe() -> None:
    result = assess_usage_budget("supabase", used=100, limit=None)

    assert result.state is CapacityState.UNKNOWN
    assert result.detail == "budget_not_configured"


def test_unavailable_usage_is_unknown() -> None:
    result = assess_usage_budget("backblaze_b2", used=None, limit=1000)

    assert result.state is CapacityState.UNKNOWN
    assert result.detail == "usage_unavailable"


def test_usage_below_low_watermark_is_ok() -> None:
    result = assess_usage_budget(
        "qdrant",
        used=800,
        limit=1000,
        low_watermark_percent=10,
    )

    assert result.state is CapacityState.OK
    assert result.detail == "budget_ok"


def test_usage_at_low_watermark_pauses_as_low() -> None:
    result = assess_usage_budget(
        "qdrant",
        used=900,
        limit=1000,
        low_watermark_percent=10,
    )

    assert result.state is CapacityState.LOW
    assert result.detail == "budget_low"


def test_usage_at_or_above_limit_is_exhausted() -> None:
    at_limit = assess_usage_budget("supabase", used=1000, limit=1000)
    above_limit = assess_usage_budget("supabase", used=1100, limit=1000)

    assert at_limit.state is CapacityState.EXHAUSTED
    assert above_limit.state is CapacityState.EXHAUSTED


def test_invalid_budget_inputs_are_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        assess_usage_budget("supabase", used=0, limit=0)
    with pytest.raises(ValueError, match="negative"):
        assess_usage_budget("supabase", used=-1, limit=100)
    with pytest.raises(ValueError, match="between 1 and 50"):
        assess_usage_budget("supabase", used=1, limit=100, low_watermark_percent=0)
