# Persisted Evidence Search

## Purpose

This post-roadmap milestone adds a protected, read-only search surface over evidence and provenance that are already persisted by the Financial Intelligence Agent.

Routes:

- `/dashboard/search` — human-readable search page
- `/dashboard/search/status` — authenticated JSON search result

The feature does not crawl the web, ingest new sources, mutate claim state, promote trust, repair cloud stores, or delete evidence.

## Search contract

Claim results can be constrained by:

- free text
- exact `source_id`
- exact claim `state`
- case-insensitive literal entity substring
- case-insensitive literal metric substring
- persisted temporal range

Free text is a case-insensitive literal substring search across persisted entity, metric, value text, evidence text, and source URL. Fuzzy similarity is intentionally disabled.

The claim temporal date is deterministic:

1. `effective_date`, when explicitly persisted;
2. otherwise `publication_date`, when explicitly persisted;
3. otherwise the claim remains undated.

Retrieval time is never substituted for publication/effective date. When a date range is requested, undated claims do not match it.

Direct document results use free text and exact source filtering only because document rows do not carry claim entity, metric, state, or publication/effective fields. Returned claim rows include linked document provenance where available.

## Provenance returned

Claim results include:

- claim/document IDs
- source ID and source URL
- original persisted metric
- exact-alias canonical indicator overlay, when available
- value/unit/state/confidence
- publication/effective/selected temporal date and basis
- quality-gate diagnostics
- bounded evidence excerpt
- linked document title, SHA-256, content type, retrieval timestamp, chunk count, status and source/final URL

Document results include the same safe provenance fields where applicable. Private B2 object keys are intentionally not returned.

## Bounds

- result limit: 1–100 per section
- offset: 0–5000
- query text: maximum 200 characters at the API boundary
- no regex search
- no fuzzy search
- no unrestricted source URLs

These bounds prevent the dashboard from becoming an unbounded database export surface.

## Security

Both routes reuse the existing dashboard HTTP Basic authentication and dashboard security-header middleware. Responses are `Cache-Control: no-store`.

The production smoke contract includes `/dashboard/search` along with the other protected workspace pages and verifies that unauthenticated access remains blocked.

## Non-goals

This feature does not:

- decide whether a candidate claim is true;
- change verification/trust state;
- infer missing dates;
- generate forecasts or trading signals;
- expose storage credentials or object keys;
- replace retained source evidence.

It is an inspection and navigation layer only.
