from app.claims.entities import normalize_metric_for_entity, resolve_entity


def test_full_rbi_name_resolves_to_canonical_entity() -> None:
    result = resolve_entity(
        "Reserve Bank of India Policy Repo Rate : 5.25%",
        default_entity="International Monetary Fund",
    )

    assert result.canonical_name == "Reserve Bank of India"
    assert result.basis == "explicit_local_alias"


def test_rbi_acronym_resolves_across_secondary_source() -> None:
    result = resolve_entity(
        "RBI\nPolicy Repo Rate\n:\n5.25%",
        default_entity="International Monetary Fund",
    )

    assert result.canonical_name == "Reserve Bank of India"
    assert "RBI" in result.matched_aliases


def test_multiple_known_entities_are_not_guessed() -> None:
    result = resolve_entity(
        "The IMF discussed RBI policy settings and the Policy Repo Rate : 5.25%",
        default_entity="International Monetary Fund",
    )

    assert result.canonical_name == "International Monetary Fund"
    assert result.basis == "ambiguous_local_entities_defaulted"
    assert set(result.ambiguous_candidates) == {
        "International Monetary Fund",
        "Reserve Bank of India",
    }


def test_no_explicit_subject_keeps_source_default() -> None:
    result = resolve_entity(
        "Policy Repo Rate : 5.25%",
        default_entity="Reserve Bank of India",
    )

    assert result.canonical_name == "Reserve Bank of India"
    assert result.basis == "source_default"


def test_default_alias_is_canonicalized() -> None:
    result = resolve_entity("Inflation : 4.00%", default_entity="IMF")

    assert result.canonical_name == "International Monetary Fund"
    assert result.basis == "source_default"


def test_short_alias_does_not_match_inside_longer_token() -> None:
    result = resolve_entity(
        "IMFunds metric : 4.00%",
        default_entity="World Bank",
    )

    assert result.canonical_name == "World Bank"
    assert result.basis == "source_default"


def test_sebi_alias_resolves_canonically() -> None:
    result = resolve_entity(
        "SEBI\nMinimum public shareholding : 25%",
        default_entity="World Bank",
    )

    assert result.canonical_name == "Securities and Exchange Board of India"
    assert result.basis == "explicit_local_alias"


def test_rbi_prefix_is_removed_from_metric_after_entity_resolution() -> None:
    metric = normalize_metric_for_entity(
        "RBI Policy Repo Rate",
        canonical_entity="Reserve Bank of India",
    )

    assert metric == "Policy Repo Rate"


def test_full_entity_prefix_is_removed_from_metric() -> None:
    metric = normalize_metric_for_entity(
        "Reserve Bank of India - Policy Repo Rate",
        canonical_entity="Reserve Bank of India",
    )

    assert metric == "Policy Repo Rate"


def test_entity_name_inside_metric_is_not_removed_when_not_leading() -> None:
    metric = normalize_metric_for_entity(
        "Exposure to RBI regulated entities",
        canonical_entity="Reserve Bank of India",
    )

    assert metric == "Exposure to RBI regulated entities"
