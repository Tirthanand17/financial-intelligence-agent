# IMF CPI Candidate — Verified Structure Milestone

## Status

This milestone remains non-operational. It does not widen the IMF source allow-list, persist IMF evidence, create a monitor, change the scheduler, or activate IMF in production.

The existing World Bank production source remains unchanged.

## Verified public IMF structure contract

Research checkpoint: 20 September 2026.

Current official IMF documentation states that IMF Data APIs support SDMX 2.1 and SDMX 3.0 and that API exploration is provided through the IMF API developer portal using a beta-portal account.

The public IMF SDMX Central registry remains reachable at `https://sdmxcentral.imf.org/sdmx/v2/`. Bounded GET-only research against that official registry established:

- dataflow: `IMF:CPI(1.0)`;
- referenced data structure: `IMF:ECOFIN_DSD(1.0)`;
- data-key dimension order: `DATA_DOMAIN`, `REF_AREA`, `INDICATOR`, `COUNTERPART_AREA`, `FREQ`;
- observation dimension: `TIME_PERIOD`;
- CPI constraint: `IMF:CPI_CONSTRAINT`;
- CPI data domain: `CPI`;
- India reference-area code: `IN`;
- all-items CPI indicator: `PCPI_IX` — `Prices, Consumer Price, All items, Index`;
- no-counterpart code required by the CPI constraint: `_Z`;
- supported CPI frequencies include annual (`A`), quarterly (`Q`) and monthly (`M`);
- `OBS_STATUS`, `BASE_PER` and `UNIT_MULT` are source metadata/attributes in the ECOFIN structure.

The public registry responses were small, bounded and read-only after broad structure expansion was rejected by the research ceiling. In particular, the global IMF indicator codelist was not accepted as a 42+ MiB response; the exact item-level `PCPI_IX` resource was used instead.

## Public data-route result and authentication gate

Two standards-compatible public data-query shapes were tested with the exact resolved key `CPI.IN.PCPI_IX._Z.M` and a three-observation bound:

- SDMX v2 context form under `/sdmx/v2/data/dataflow/IMF/CPI/1.0/...`;
- SDMX 2.1/Fusion-compatible form under `/sdmx/v2/data/IMF,CPI,1.0/...`.

Both public SDMX Central data routes returned HTTP `501 Not Implemented`. No evidence or cloud write was performed.

The current IMF CPI dataset page links API access to `portal.api.imf.org`, and the official IMF API page explicitly requires signing in with a beta-portal account to explore the Swagger API. The exact authenticated IMF Data API endpoint, authentication scheme and query contract therefore remain unverified and must not be guessed.

## Implemented offline contract

`app/sources/imf.py` now encodes only the structure facts independently verified from the public IMF registry:

- `IMF_CPI_DSD_ID = ECOFIN_DSD`;
- `IMF_CPI_DATA_DOMAIN = CPI`;
- `IMF_CPI_INDIA_REF_AREA = IN`;
- `IMF_CPI_ALL_ITEMS_INDICATOR = PCPI_IX`;
- `IMF_CPI_NO_COUNTERPART_AREA = _Z`.

The bounded SDMX-CSV parser requires the full verified key fields by name, rejects a wrong domain/area/indicator/counterpart, permits only annual/quarterly/monthly periods with matching syntax, caps rows at 12, rejects duplicate observations, preserves exact input bytes, retains missing values, and never maps `TIME_PERIOD` to `publication_date` or `effective_date`.

Explicit `OBS_STATUS=F` remains ineligible for factual mapping. No structured claim is created by this adapter.

## Still blocked

The following gates intentionally remain false:

- authenticated IMF Data API endpoint/query contract validated;
- IMF API authentication configured;
- candidate data host allow-listed for ingestion;
- persistence path implemented;
- live canary runner implemented;
- PostgreSQL/B2/Qdrant reconciliation validated;
- bounded live canary passed;
- production monitor created;
- scheduler integration;
- IMF production activation.

No current production source or scheduler behavior changes in this milestone.

## Next safe milestone

The next step requires authorized IMF API access. After the user signs into or creates the IMF beta API portal account, the project should inspect the current Swagger definition to establish the exact SDMX 2.1/3.0 base URL, authentication requirement and CPI data-query shape. Secrets must be entered by the user directly into the provider/GitHub secret UI and must never be pasted into chat.

Only after that contract is verified should a fresh branch add a fixed India/all-items CPI URL builder, strict response validation, source-policy review, exact-byte persistence/reconciliation, and then a separate one-shot live canary with safe capacity and `TRUST_PROMOTION_ENABLED=false`.
