from app.claims.eligibility import claim_quality_rejection_reason


def test_contact_and_page_metadata_are_rejected_without_broad_substring_filtering() -> None:
    rejected = {
        "Email": "metadata_metric",
        "Fax No": "metadata_metric",
        "Telephone Number": "metadata_metric",
        "Website URL": "metadata_metric",
        "GSTIN": "metadata_metric",
        "Last Updated": "metadata_metric",
        "Page No. 12": "metadata_metric",
        "Serial No 7": "metadata_metric",
    }
    for metric, reason in rejected.items():
        assert claim_quality_rejection_reason(metric, f"{metric}: 123") == reason

    for metric in (
        "Time Deposit Rate",
        "GST Collections",
        "Page Industries Revenue",
        "10-Year G-Sec Yield",
        "Tier 1 Capital Ratio",
        "M3 Growth",
    ):
        assert claim_quality_rejection_reason(metric, f"{metric}: 5.25%") is None
