from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ClaimState(str, Enum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    TRUSTED = "trusted"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"
    SUPERSEDED = "superseded"


class StructuredClaim(BaseModel):
    """Canonical representation of one source-grounded financial claim.

    `value_text` preserves what the source says. `value_numeric` is optional and
    is used only when the claim has a safely parsed numeric value.

    Entity-attribution fields are derivation provenance rather than claim
    identity. They let Phase 3 persist why a canonical subject was assigned
    without altering the already-deployed `claims` table or pretending older
    manually-created claims have attribution evidence they do not have.
    """

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    entity: str = Field(min_length=1, max_length=255)
    metric: str = Field(min_length=1, max_length=255)
    value_text: str = Field(min_length=1, max_length=500)
    value_numeric: Decimal | None = None
    unit: str | None = Field(default=None, max_length=64)

    publication_date: date | None = None
    effective_date: date | None = None

    source_id: str = Field(min_length=1, max_length=64)
    source_url: str = Field(min_length=1)
    document_id: str = Field(min_length=1, max_length=36)
    evidence_text: str = Field(min_length=1)
    evidence_chunk_index: int = Field(ge=0)

    # Transient Phase 3 derivation provenance. These fields are persisted in a
    # separate attribution table by the storage layer when the extractor has
    # supplied an actual attribution decision.
    entity_attribution_basis: str = Field(default="unspecified", min_length=1, max_length=64)
    entity_source_default: str | None = Field(default=None, max_length=255)
    entity_matched_aliases: tuple[str, ...] = ()
    entity_ambiguous_candidates: tuple[str, ...] = ()
    entity_evidence_text: str | None = None

    confidence: float = Field(ge=0.0, le=1.0)
    state: ClaimState = ClaimState.CANDIDATE
