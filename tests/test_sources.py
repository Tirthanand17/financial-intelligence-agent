import pytest

from app.sources.registry import get_source, validate_source_url


def test_rbi_source_is_authority_a() -> None:
    source = get_source("rbi")
    assert source.authority_level.value == "A"


def test_rbi_official_hosts_are_allowed() -> None:
    source = validate_source_url("rbi", "https://bulletin.rbi.org.in/")
    assert source.source_id == "rbi"


def test_untrusted_host_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_source_url("rbi", "https://example.com/fake-rbi-report.pdf")


def test_non_https_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_source_url("rbi", "http://www.rbi.org.in/")
