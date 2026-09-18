# Read-Only Incident Center

## Purpose

The Incident Center turns existing fail-closed readiness facts into deterministic operator alerts. It is an inspection layer only; it does not repair state, run ingestion, alter scheduler cadence, change claim/trust state, or send notifications to an external recipient.

## Protected surfaces

- `GET /dashboard/incidents` — human-readable incident center.
- `GET /dashboard/incidents/status` — protected JSON snapshot.
- `GET /api/v1/incidents` — versioned protected read-only API.

All routes reuse dashboard HTTP Basic authentication and are non-cacheable.

## Deterministic incident codes

The initial evaluator can surface:

- `CAPACITY_UNSAFE` — a configured capacity measurement is unsafe or unavailable;
- `QDRANT_POINT_MISMATCH` — expected and actual vector counts do not reconcile;
- `UNEXPECTED_TRUST_EVENTS` — trust events exist while promotion is expected to stay disabled;
- `RUNTIME_GATE_DRIFT` — monitoring, auto-ingest, or trust gates differ from safe defaults outside the bounded scheduler step;
- `CLOUD_MEASUREMENT_UNAVAILABLE` — required cloud measurements or Qdrant reconciliation are unavailable;
- `QUEUE_FAILED_ITEMS` — failed queue items are persisted;
- `SOURCE_MONITOR_NOT_READY` — a source monitor is not ready or has consecutive failures;
- `RECENT_MONITOR_RUN_FAILED` — a recent persisted source-monitor run failed.

Critical incidents make the incident snapshot `blocked`; high-severity incidents make it `attention`; otherwise it is `clear`.

## Notification delivery

The evaluator reports `notification_delivery_configured=false`. This is deliberate. No email, SMS, webhook, or paid alerting service is configured without an explicitly approved channel and recipient. GitHub Actions remains the existing execution/failure signal, while this page provides a deterministic project-level incident view.

## Safety boundary

The Incident Center does not:

- write PostgreSQL, B2, or Qdrant;
- delete or rewrite evidence;
- enable trust promotion;
- change runtime gates;
- trigger source discovery or ingestion;
- change scheduler frequency;
- auto-repair reconciliation mismatches;
- suppress an unsafe condition to make the dashboard appear healthy.

Unknown or unavailable safety measurements remain attention/blocking conditions through the underlying readiness logic.
