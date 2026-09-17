# Post-Roadmap Claim Verification Workbench

## Purpose

This milestone adds a protected, read-only workbench for understanding the claim lifecycle already implemented by the Financial Intelligence Agent. It does not create a new numbered phase and does not change the validated ingestion or trust boundaries.

The workbench answers operational questions such as:

- Why is a claim still `candidate`?
- Which independent source groups support the same fact?
- Is there active conflicting evidence?
- Did the structured-claim quality gate block the claim?
- What state would the existing verification policy reconcile to if run?
- Is a currently `verified` claim eligible under the existing trust policy, without actually promoting it?
- What verification/trust audit event was recorded most recently?
- Was the claim superseded by a later source-local version, or did it supersede older history?
- What entity-attribution basis is available for trust policy auditing?

## Protected routes

The existing dashboard HTTP Basic authentication protects both routes:

```text
GET /dashboard/verification
GET /dashboard/verification/status
```

The HTML page is the operator view. The status route is a JSON diagnostic endpoint used by the page.

Optional JSON filters:

```text
source_id=<registered source id>
state=candidate|verified|trusted|rejected|conflicted|superseded
limit=1..200
```

Responses use `Cache-Control: no-store`.

## Diagnostic inputs

The workbench reads the existing PostgreSQL records only:

- `claims`
- `claim_entity_attributions`
- `claim_verification_events`
- `claim_trust_events`
- `claim_supersessions`

It also reuses the existing pure policy functions:

- structured-claim quality eligibility;
- independent-source verification/conflict assessment; and
- conservative trust assessment.

No source is fetched and no language model is called.

## Main outputs

For each visible claim the workbench reports:

- current persisted state;
- evidence-assessed verification state;
- safe reconciliation state, preserving an existing trusted state unless a conflict is detected;
- verification reason;
- quality gate status and rejection reason;
- source authority level/category/independence group;
- publication/effective dates and confidence;
- supporting and conflicting source IDs and independence groups;
- read-only trust diagnostic and corroborating sources;
- entity-attribution basis and aliases;
- latest verification event;
- latest trust event;
- supersession relationship/history;
- source URL and a bounded evidence excerpt.

The summary highlights actionable review items, claims ready for verification reconciliation, trust-policy-eligible verified claims, conflicts, quality-blocked claims, and audit-event counts.

## Safety boundary

The workbench is deliberately incapable of changing production knowledge. It does **not**:

- mutate claim state;
- create verification events;
- create trust events;
- promote `verified` to `trusted`;
- resolve conflicts;
- change supersession history;
- edit entity attribution;
- ingest documents;
- alter scheduler cadence;
- delete evidence or history;
- write to Qdrant or Backblaze B2; or
- generate trading signals, forecasts, recommendations, or orders.

A positive trust diagnostic means only that the already-implemented pure trust policy sees the currently persisted evidence as qualifying. The workbench never executes the promotion.

## Operator interpretation

`independent_sources_disagree`
: Independent source groups contain different values for the same entity/metric/unit/temporal scope. Treat this as a conflict requiring evidence review.

`quality_gate_failed`
: The claim is preserved historically but cannot be used to create new verified/trusted knowledge under the current quality floor.

`missing_temporal_scope`
: The fact has no safe publication/effective date for exact temporal comparison.

`insufficient_independent_sources`
: The claim has not yet been corroborated by a separate independence group.

`independent_sources_agree`
: The persisted evidence is sufficient for the existing verification policy to assess `verified`. The workbench itself still performs no transition.

`terminal_state_preserved`
: Rejected or superseded history remains preserved.

## Validation

Regression tests verify that:

- verification and trust diagnostics do not mutate persisted claim state;
- a verified authority-A primary claim with qualified independent corroboration is reported as trust-policy eligible without creating a trust event;
- insufficient independent evidence remains visible as actionable;
- verification/trust audit history and supersession links are surfaced correctly;
- source/state filters are applied to the operator view;
- both routes reuse the existing dashboard authentication; and
- the HTML contains no ingestion, POST, trust-promotion, or other write controls.

## Next boundary

This milestone improves observability only. Any future feature that allows an operator to approve/reject a claim, change claim state, enable trust promotion, or otherwise write through the dashboard requires a separate design, explicit authorization model, CSRF/session protection, audit requirements, and a dedicated production approval decision.
