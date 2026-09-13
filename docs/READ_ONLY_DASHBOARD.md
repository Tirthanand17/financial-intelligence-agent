# Private Read-Only Dashboard

The application now includes a protected operational dashboard at `/dashboard` and a JSON status endpoint at `/dashboard/status`.

## Safety model

The dashboard is read-only. It does not expose ingestion controls, scheduler controls, trust-promotion controls, provider credentials, API keys, database URLs, object-store keys, or raw secret values.

Both dashboard credentials must be configured through deployment secrets:

```text
DASHBOARD_USERNAME=<private operator username>
DASHBOARD_PASSWORD=<strong private password>
```

If either value is missing, the dashboard fails closed with HTTP 503. Invalid or absent HTTP Basic credentials receive HTTP 401.

## What the dashboard shows

- overall status: healthy / warning / blocked;
- document and claim counts;
- expected and actual Qdrant point counts;
- pending/ingested/duplicate/rejected/failed queue counts;
- trust-event count;
- measured Supabase, Backblaze B2 and Qdrant capacity state;
- each registered monitor's current state and last success time; and
- the latest monitor runs and bounded ingestion counts.

The page refreshes automatically every five minutes and also provides a manual refresh button.

## Integrity boundary

The dashboard checks structural state, Qdrant point reconciliation and measured capacity. It deliberately does not download every stored evidence object on every page view. Full evidence-hash verification remains in the fail-closed production-readiness workflow that runs before and after scheduled ingestion.

## Deployment boundary

The dashboard can be deployed behind HTTPS on the same FastAPI application. Do not expose it publicly without authentication. Prefer a private deployment or an additional reverse-proxy/identity layer if the application becomes internet-facing.

The existing scheduler and ingestion limits remain unchanged by this dashboard feature.
