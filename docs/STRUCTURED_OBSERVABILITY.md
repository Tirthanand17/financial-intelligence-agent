# Structured Observability

## Purpose

This post-roadmap hardening adds secret-minimized HTTP request correlation and structured timing logs without changing ingestion, evidence, scheduler, trust, or storage behavior.

## Request correlation

Every HTTP request receives a new server-generated 32-character hexadecimal request ID. The ID is returned in the `X-Request-ID` response header and is placed in a request-local context while the request is executing.

Caller-supplied request IDs are deliberately not trusted or reused. This prevents untrusted values from becoming log-correlation identifiers.

## Structured request event

One compact JSON event is emitted for each completed request with:

- event type;
- server-generated request ID;
- HTTP method;
- URL path only;
- response status code;
- elapsed processing time in milliseconds;
- outcome (`completed` or `exception`);
- safe runtime correlation metadata when the platform supplies it, such as Render Git commit or GitHub Actions run ID.

For unhandled exceptions the event records only the exception class name, not its message.

## Secret minimization

The observability layer intentionally does **not** log:

- query strings;
- request or response bodies;
- Authorization headers;
- cookies;
- dashboard usernames or passwords;
- client IP addresses;
- database URLs;
- Qdrant credentials;
- B2/S3 credentials;
- environment-secret values;
- exception messages.

This means a query parameter can contain sensitive text without that text being copied into the request log event.

## Scheduler/run correlation

GitHub Actions already supplies native run IDs for scheduled operational cycles. When `GITHUB_RUN_ID`, `GITHUB_RUN_ATTEMPT`, or `GITHUB_WORKFLOW` is available to a process, the same non-secret metadata can be included in structured events. Render deployments may contribute `RENDER_GIT_COMMIT` or `RENDER_INSTANCE_ID` when available.

## Safety boundary

Observability is logging and response-header instrumentation only. It does not:

- mutate PostgreSQL, B2, or Qdrant;
- change evidence or claim state;
- enable trust promotion;
- alter scheduler cadence;
- run source discovery or ingestion;
- add remote telemetry vendors;
- transmit secrets to an external analytics service;
- add trading or forecasting behavior.

The implementation uses the existing application stdout/log stream, so it does not create a new paid infrastructure dependency.
