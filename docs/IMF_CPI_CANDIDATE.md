# IMF CPI Candidate — Offline Adapter Milestone

## Status

This milestone is intentionally offline and non-operational. It does not widen the IMF source allow-list, fetch IMF data, persist evidence, create a monitor, change the scheduler, or activate IMF in production.

The existing World Bank production source remains unchanged.

## Current official-source findings

Research checkpoint: 20 September 2026.

The IMF Data Portal states that IMF data are available through SDMX 2.1 and SDMX 3.0 APIs and directs users to an authenticated Swagger portal for API exploration.

The IMF also continues to operate IMF SDMX Central at `https://sdmxcentral.imf.org/`, whose REST web-service entry is `https://sdmxcentral.imf.org/sdmx/v2/`.

IMF's current IFS migration guidance says the former monolithic International Financial Statistics dataset is discontinued as a single dataset and that its consumer-price series now live in the Consumer Price Index (CPI) dataset.

The official IMF SDMX Central guidance identifies:

- dataflow: `IMF:CPI(1.0)` — Consumer Price Index;
- all-items CPI indicator: `PCPI_IX`;
- time frequency codes including annual (`A`), quarterly (`Q`) and monthly (`M`);
- `OBS_STATUS` as an observation attribute;
- `TIME_PERIOD` as an observation period rather than a publication/effective date.

## Implemented offline contract

`app/sources/imf.py` provides a bounded SDMX-CSV parser for the CPI candidate.

It requires named columns rather than relying on positional guessing:

- `FREQ`;
- `REF_AREA`;
- `INDICATOR`;
- `TIME_PERIOD`;
- `OBS_VALUE`.

It also preserves optional source metadata when present:

- `OBS_STATUS`;
- `BASE_PER`;
- `UNIT_MULT`;
- `COUNTERPART_AREA`.

The parser:

- accepts only `PCPI_IX` for this milestone;
- requires an explicitly expected reference-area code supplied by the caller;
- permits only annual, quarterly or monthly periods with matching syntax;
- caps accepted rows at 12;
- rejects duplicate observation keys;
- retains missing values without inventing replacements;
- treats explicit `OBS_STATUS=F` observations as forecast and not fact-eligible;
- preserves the exact input bytes on the parsed result;
- never maps `TIME_PERIOD` to `publication_date` or `effective_date`;
- performs no network I/O and no storage writes.

The reference-area code is deliberately not hard-coded yet. The exact production API/query contract must prove the current IMF country coding for the selected live endpoint before India is fixed into a URL builder.

## Still blocked

The following gates intentionally remain false:

- candidate host allow-listed;
- exact bounded live query contract validated;
- persistence path implemented;
- live canary runner implemented;
- PostgreSQL/B2/Qdrant reconciliation validated;
- bounded live canary passed;
- production monitor created;
- scheduler integration;
- IMF production activation.

`sdmxcentral.imf.org` therefore remains outside `app.sources.registry` for the IMF source.

## Next safe milestone

Before any source-policy widening or live write:

1. resolve the exact supported current IMF dissemination endpoint and authentication requirements;
2. resolve the exact CPI dataflow/version and India reference-area code on that endpoint;
3. build one fixed, bounded query for all-items CPI only;
4. reject redirects, oversize responses, unexpected content types, areas, indicators, frequencies and response shapes;
5. add exact-byte persistence with SHA-256 replay verification and PostgreSQL/B2/Qdrant reconciliation;
6. create a separate one-shot canary requiring explicit network/write flags;
7. run the canary once with safe capacity and `TRUST_PROMOTION_ENABLED=false`;
8. only after clean reconciliation consider a separate source-policy/production-activation decision.

Any ambiguity in API ownership, authentication, country coding, temporal semantics, or response structure remains a blocker rather than being guessed around.
