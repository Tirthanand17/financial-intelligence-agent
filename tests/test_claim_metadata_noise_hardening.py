from app.claims.eligibility import claim_quality_rejection_reason


def test_exact_contact_and_page_metadata_labels_are_rejected() -> None:
    for metric in (
        "Email",
        "Email ID",
        "Fax No",
        "Telephone Number",
        "Website",
        "Website URL",
        "Page No",
        "Page Number",
        "Serial No",
        "Sr. No",
        "S. No",
        "Time",
        "Last Updated",
        "GSTIN",
        "Toll Free Number",
    ):
        assert claim_quality_rejection_reason(metric, f"{metric}: 12345") == "metadata_metric"


def test_metadata_stems_with_numeric_suffix_are_rejected() -> None:
    for metric in ("Page 2", "Page No. 7", "Serial Number 4", "Sr. No. 8", "S. No. 9"):
        assert claim_quality_rejection_reason(metric, f"{metric}: 1") == "metadata_metric"


def test_legitimate_financial_labels_are_not_overblocked() -> None:
    for metric in (
        "Page Industries Revenue",
        "Time Deposit Rate",
        "Serial Bond Coupon",
        "Email Services Revenue",
        "Website Advertising Revenue",
        "GST Collections",
        "Telephone Services CPI",
    ):
        assert claim_quality_rejection_reason(metric, f"{metric}: 5.25%") is None
