# Post-Roadmap Intelligence Dashboard UI

This milestone adds a human-readable, protected intelligence view on top of the existing read-only intelligence snapshot.

## Purpose

The operational dashboard answers whether the system is healthy. The intelligence view answers what evidence the system currently holds, without changing any data or generating market predictions.

## Routes

- `/dashboard` — operational health dashboard.
- `/dashboard/status` — operational health JSON.
- `/dashboard/intelligence` — read-only intelligence JSON.
- `/dashboard/intelligence-view` — human-readable intelligence UI.

All four routes use the same HTTP Basic authentication boundary.

## Intelligence UI contents

The UI shows:

- total documents and claims in the selected scope;
- active quality-safe claim count;
- candidate, verified/trusted, conflicted and quality-filtered claim counts;
- source coverage by documents and claims;
- claim-state distribution;
- latest active quality-safe claims with entity, metric, value, state, confidence, dates, evidence excerpt and source link;
- conflicts requiring attention;
- recent indexed documents; and
- explicit safety notes explaining candidate and trust boundaries.

The page can filter the read-only snapshot by source ID and can change the displayed result limit. These controls only change the GET query used to read data.

## Safety boundary

This feature does not:

- fetch new source documents;
- process or ingest queue items;
- mutate claims;
- promote trust;
- change scheduler cadence or limits;
- alter Supabase, B2 or Qdrant data;
- produce market forecasts, trading signals or financial recommendations.

It reuses the existing `/dashboard/intelligence` endpoint and the Phase 16 quality filter. All historical evidence and claim rows remain preserved.
