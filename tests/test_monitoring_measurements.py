from types import SimpleNamespace

from app.monitoring.measurements import (
    CloudBudgetLimits,
    CloudUsage,
    assess_measured_capacity,
    measure_cloud_usage,
)
from app.monitoring.models import CapacityState


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _Session:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def execute(self, statement):
        self.calls += 1
        return _ScalarResult(self.value)


class _S3:
    def __init__(self):
        self.calls = []

    def list_object_versions(self, **kwargs):
        self.calls.append(kwargs)
        if "KeyMarker" not in kwargs:
            return {
                "Versions": [
                    {"Key": "a", "VersionId": "v2", "Size": 100},
                    {"Key": "a", "VersionId": "v1", "Size": 200},
                ],
                "DeleteMarkers": [{"Key": "gone", "VersionId": "d1"}],
                "IsTruncated": True,
                "NextKeyMarker": "a",
                "NextVersionIdMarker": "v1",
            }
        return {
            "Versions": [{"Key": "b", "VersionId": "v1", "Size": 300}],
            "IsTruncated": False,
        }


class _Qdrant:
    def __init__(self, points_count=12):
        self.points_count = points_count
        self.calls = []

    def get_collection(self, collection):
        self.calls.append(collection)
        return SimpleNamespace(points_count=self.points_count)


def test_measure_cloud_usage_reads_all_b2_versions_without_object_downloads() -> None:
    session = _Session(1_048_576)
    s3 = _S3()
    qdrant = _Qdrant(points_count=25)

    usage = measure_cloud_usage(
        session,
        s3_client=s3,
        qdrant_client=qdrant,
        s3_bucket="evidence",
        qdrant_collection="financial_knowledge",
    )

    assert usage.supabase_bytes == 1_048_576
    # Both versions of key "a" count, plus key "b". Delete markers add no bytes.
    assert usage.backblaze_b2_bytes == 600
    assert usage.qdrant_points == 25
    assert session.calls == 1
    assert len(s3.calls) == 2
    assert all(call["Bucket"] == "evidence" for call in s3.calls)
    assert s3.calls[1]["KeyMarker"] == "a"
    assert s3.calls[1]["VersionIdMarker"] == "v1"
    assert qdrant.calls == ["financial_knowledge"]


def test_b2_version_pagination_without_version_marker_is_supported() -> None:
    class S3NoVersionMarker:
        def __init__(self):
            self.calls = []

        def list_object_versions(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return {
                    "Versions": [{"Size": 10}],
                    "IsTruncated": True,
                    "NextKeyMarker": "next-key",
                }
            return {"Versions": [{"Size": 20}], "IsTruncated": False}

    s3 = S3NoVersionMarker()
    usage = measure_cloud_usage(
        _Session(1),
        s3_client=s3,
        qdrant_client=_Qdrant(1),
        s3_bucket="evidence",
        qdrant_collection="financial_knowledge",
    )

    assert usage.backblaze_b2_bytes == 30
    assert s3.calls[1]["KeyMarker"] == "next-key"
    assert "VersionIdMarker" not in s3.calls[1]


def test_measurement_failures_become_unknown_instead_of_guesses() -> None:
    class BrokenSession:
        def execute(self, statement):
            raise RuntimeError("database unavailable")

    class BrokenS3:
        def list_object_versions(self, **kwargs):
            raise RuntimeError("storage unavailable")

    class BrokenQdrant:
        def get_collection(self, collection):
            raise RuntimeError("vector unavailable")

    usage = measure_cloud_usage(
        BrokenSession(),
        s3_client=BrokenS3(),
        qdrant_client=BrokenQdrant(),
        s3_bucket="evidence",
        qdrant_collection="financial_knowledge",
    )

    assert usage == CloudUsage(
        supabase_bytes=None,
        backblaze_b2_bytes=None,
        qdrant_points=None,
    )


def test_missing_operator_limits_fail_closed_even_with_measured_usage() -> None:
    services, decision = assess_measured_capacity(
        CloudUsage(
            supabase_bytes=1_000,
            backblaze_b2_bytes=2_000,
            qdrant_points=3,
        ),
        CloudBudgetLimits(
            supabase_max_mb=None,
            backblaze_b2_max_mb=None,
            qdrant_max_points=None,
        ),
    )

    assert all(service.state is CapacityState.UNKNOWN for service in services)
    assert decision.allow_ingestion is False
    assert decision.reason == "cloud_capacity_unknown"
    assert set(decision.blocking_services) == {"supabase", "backblaze_b2", "qdrant"}


def test_explicit_limits_convert_measured_usage_to_safe_capacity() -> None:
    services, decision = assess_measured_capacity(
        CloudUsage(
            supabase_bytes=50 * 1024 * 1024,
            backblaze_b2_bytes=25 * 1024 * 1024,
            qdrant_points=100,
        ),
        CloudBudgetLimits(
            supabase_max_mb=500,
            backblaze_b2_max_mb=500,
            qdrant_max_points=10_000,
            low_watermark_percent=10,
        ),
    )

    assert [service.state for service in services] == [
        CapacityState.OK,
        CapacityState.OK,
        CapacityState.OK,
    ]
    assert decision.allow_ingestion is True
    assert decision.reason == "all_required_cloud_capacity_ok"


def test_low_remaining_budget_pauses_work() -> None:
    services, decision = assess_measured_capacity(
        CloudUsage(
            supabase_bytes=95 * 1024 * 1024,
            backblaze_b2_bytes=10 * 1024 * 1024,
            qdrant_points=100,
        ),
        CloudBudgetLimits(
            supabase_max_mb=100,
            backblaze_b2_max_mb=100,
            qdrant_max_points=1_000,
            low_watermark_percent=10,
        ),
    )

    by_name = {service.service: service.state for service in services}
    assert by_name["supabase"] is CapacityState.LOW
    assert decision.allow_ingestion is False
    assert decision.reason == "cloud_capacity_low"
    assert decision.blocking_services == ("supabase",)
