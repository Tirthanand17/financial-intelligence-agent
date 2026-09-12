from datetime import date
from decimal import Decimal

from app.claims.extractor import extract_structured_claims
from app.ingestion.extractor import extract_document


RSS = b'''<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Reserve Bank of India - Press Releases</title>
    <item>
      <title>Governor's Statement: June 05, 2026</title>
      <link>https://www.rbi.org.in/example</link>
      <pubDate>Fri, 05 Jun 2026 06:30:00 GMT</pubDate>
      <description><![CDATA[
        The RBI Governor said the policy repo rate remains at 5.25% with a neutral stance.
      ]]></description>
    </item>
  </channel>
</rss>
'''


def test_extracts_rss_item_date_and_description_without_following_link() -> None:
    document = extract_document(RSS, "text/xml")

    assert document.title == "Reserve Bank of India - Press Releases"
    assert "Governor's Statement: June 05, 2026" in document.text
    assert "Published on 05 June 2026" in document.text
    assert "policy repo rate remains at 5.25%" in document.text
    assert "Item Link https://www.rbi.org.in/example" in document.text


def test_rss_item_date_scopes_repo_rate_claim_locally() -> None:
    document = extract_document(RSS, "application/rss+xml")
    claims = extract_structured_claims(
        chunks=[document.text],
        document_id="11111111-1111-1111-1111-111111111111",
        source_id="rbi",
        source_url="https://rbi.org.in/pressreleases_rss.xml",
        entity="Reserve Bank of India",
    )

    repo_claims = [claim for claim in claims if claim.metric == "Policy Repo Rate"]

    assert len(repo_claims) == 1
    claim = repo_claims[0]
    assert claim.entity == "Reserve Bank of India"
    assert claim.value_numeric == Decimal("5.25")
    assert claim.unit == "%"
    assert claim.publication_date == date(2026, 6, 5)
