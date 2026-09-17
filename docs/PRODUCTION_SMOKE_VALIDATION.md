# Production Smoke Validation

This post-roadmap hardening milestone adds a non-destructive production smoke contract for the deployed Render service.

## What it checks

The validator checks the public `/health` endpoint and the protected read-only dashboard surfaces:

- `/dashboard/hub`
- `/dashboard`
- `/dashboard/readiness`
- `/dashboard/intelligence-view`
- `/dashboard/verification`
- `/dashboard/timeline`

Without credentials, every protected surface must return HTTP 401 and retain the dashboard security contract: `Cache-Control: no-store`, CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and a Basic-auth challenge.

If both `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` are available as GitHub Actions secrets, the same validator also requires HTTP 200 from every protected surface. Credentials are placed only in the Authorization header and are never printed.

## Safety boundaries

The smoke check is GET-only. It does not call `/ingest`, does not run source monitoring, does not process the queue, does not mutate claim state, does not enable trust promotion, does not repair stores, and does not delete evidence.

The workflow is manual (`workflow_dispatch`) so it does not change scheduler cadence or create another recurring job.

## Fail-closed behavior

The command exits non-zero when the health payload is wrong, a protected route is unexpectedly public, a required browser-security header is absent, authenticated access fails when credentials are supplied, the base URL is not HTTPS, only one credential is configured, or a network failure prevents validation.

Run locally or from the manual GitHub workflow with:

```bash
python scripts/production_smoke.py
```

No credential values should ever be copied into source files, workflow YAML, issues, or logs.
