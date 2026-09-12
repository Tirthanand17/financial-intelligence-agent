import pytest

from app.sources.registry import get_source, validate_source_url


def test_rbi_source_is_authority_a() -> None:
    source = get_source("rbi")
    assert source.authority_level.value == "A"


def test_rbi_official_hosts_are_allowed() -> None:
    source = validate_source_url("rbi", "https://bulletin.rbi.org.in/")
    assert source.source_id == "rbi"


def test_ddnews_is_authority_b_government_broadcaster() -> None:
    source = get_source("ddnews")
    assert source.authority_level.value == "B"
    assert source.category == "government_public_broadcaster"


def test_ddnews_official_host_is_allowed() -> None:
    source = validate_source_url(
        "ddnews",
        "https://ddnews.gov.in/en/example-article/",
    )
    assert source.source_id == "ddnews"


def test_untrusted_host_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_source_url("rbi", "https://example.com/fake-rbi-report.pdf")


def test_ddnews_lookalike_host_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_source_url("ddnews", "https://ddnews.gov.in.example.com/fake")


def test_non_https_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_source_url("rbi", "http://www.rbi.org.in/")
