from app.claims.extractor import extract_structured_claims
from app.claims.models import ClaimState
from app.claims.trust import assess_trust
from app.claims.verification import assess_claim
from app.sources.metadata import extract_source_publication_date


def test_dated_rbi_and_ddnews_repo_rate_flow_can_reach_trusted() -> None:
    """Exercise the full pure-logic path with June 5 source-format evidence.

    This is intentionally not a live-network test. It verifies that the exact
    source-specific date shapes and the real reported 5.25% repo-rate wording
    can align without using retrieval time or broad prose inference.
    """
    rbi_text = (
        "Reserve Bank of India\n"
        "Date : Jun 05, 2026\n"
        "Policy Repo Rate : 5.25%"
    )
    ddnews_text = (
        "05/06/26 | 12:23 pm | Monetary Policy Committee (MPC) | "
        "repo rate unchanged at 5.25% | Reserve Bank of India (RBI)\n"
        "RBI keeps repo rate unchanged at 5.25%; retains neutral stance"
    )

    rbi_date = extract_source_publication_date("rbi", rbi_text)
    ddnews_date = extract_source_publication_date("ddnews", ddnews_text)

    assert rbi_date is not None
    assert rbi_date == ddnews_date

    rbi_claims = extract_structured_claims(
        chunks=[rbi_text],
        document_id="11111111-1111-1111-1111-111111111111",
        source_id="rbi",
        source_url="https://www.rbi.org.in/example",
        entity="Reserve Bank of India",
        publication_date=rbi_date,
    )
    ddnews_claims = extract_structured_claims(
        chunks=[ddnews_text],
        document_id="22222222-2222-2222-2222-222222222222",
        source_id="ddnews",
        source_url="https://ddnews.gov.in/en/example/",
        entity="DD News",
        publication_date=ddnews_date,
    )

    rbi_repo = next(claim for claim in rbi_claims if claim.metric == "Policy Repo Rate")
    ddnews_repo = next(
        claim for claim in ddnews_claims if claim.metric == "Policy Repo Rate"
    )

    assert rbi_repo.entity == "Reserve Bank of India"
    assert ddnews_repo.entity == "Reserve Bank of India"
    assert ddnews_repo.entity_attribution_basis == "explicit_local_alias"

    evidence = [rbi_repo, ddnews_repo]
    rbi_verification = assess_claim(rbi_repo, evidence)
    ddnews_verification = assess_claim(ddnews_repo, evidence)

    assert rbi_verification.state is ClaimState.VERIFIED
    assert ddnews_verification.state is ClaimState.VERIFIED

    verified_rbi = rbi_repo.model_copy(update={"state": ClaimState.VERIFIED})
    verified_ddnews = ddnews_repo.model_copy(update={"state": ClaimState.VERIFIED})

    trust = assess_trust(verified_rbi, [verified_rbi, verified_ddnews])

    assert trust.state is ClaimState.TRUSTED
    assert trust.corroborating_source_ids == ("ddnews",)
