# Optional Read-Only Access Role

## Purpose

This post-roadmap access-control milestone adds an optional inspection-only identity without changing the existing operator identity, scheduler, evidence pipeline, trust policy, or production data.

The feature is **inactive by default**. When the new read-only username/password are both unset, the application behaves exactly as before: only the existing operator dashboard credentials can access protected surfaces.

## Roles

### Operator

Configured with the existing deployment secrets:

- `DASHBOARD_USERNAME`
- `DASHBOARD_PASSWORD`

The operator can access protected read surfaces and the existing operator-only private POST routes:

- `POST /ingest`
- `POST /ask`

### Optional read-only identity

Configured only when another person needs inspection access:

- `DASHBOARD_READONLY_USERNAME`
- `DASHBOARD_READONLY_PASSWORD`

This identity can access protected GET dashboard and `/api/v1` evidence surfaces that already depend on `require_dashboard_auth`.

It cannot authenticate to `POST /ingest` or `POST /ask`; those routes now explicitly require the operator identity through `require_operator_auth`.

## Fail-closed behavior

- The operator username/password remain mandatory for protected routes.
- If the optional read-only username and password are both absent, single-operator behavior is preserved.
- If exactly one optional read-only credential is configured, settings validation rejects the configuration and the read-auth dependency also fails closed with HTTP 503 if an incomplete settings object reaches it.
- Missing or invalid credentials return HTTP 401 with the existing Basic authentication challenge.
- Secret values are never returned by the application or committed to the repository.

## Non-goals

This milestone does not create users in a database, add password-reset flows, add sessions/cookies, expose write controls, change source monitoring, alter scheduler cadence, enable trust promotion, mutate claim state, delete evidence, or add paid infrastructure.

It is deliberately a minimal two-role boundary for the current private deployment. A future multi-user identity-provider integration would be a separate security project.

## Deployment policy

Do not add the optional read-only secrets merely because this code is deployed. Leave them unset unless inspection access for another person is actually required. If enabled later, both values must be configured together using the deployment provider's secret environment settings; never commit real credentials to `.env.example` or source control.

## Validation

Regression tests verify that:

- the optional read-only identity can access protected GET dashboard and `/api/v1` surfaces;
- it cannot reach either operator-only POST service;
- the existing operator retains full current behavior;
- leaving the optional role unset preserves the existing single-operator contract; and
- partial optional configuration fails closed.
