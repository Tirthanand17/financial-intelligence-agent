# Operational Failure Alerting

## Purpose

The daily bounded scheduler already fails closed when configuration, readiness, source processing, or post-run reconciliation fails. This milestone adds a zero-cost notification path inside the existing private GitHub repository so a failed unattended cycle is harder to miss.

## Trigger

The alert job runs only when the `scheduled-cycle` job concludes with `failure`.

It does not run for successful cycles and does not alter the existing 09:30 Asia/Kolkata schedule, source order, processing limits, concurrency, readiness checks, or trust policy.

## Delivery

The workflow creates one private repository issue with the stable title:

`[Operational Alert] Scheduled financial-intelligence cycle failed`

Later failures reuse the same open issue by adding a comment instead of creating a new issue every day. If the issue has been closed and a later failure occurs, a new issue is created.

The issue contains only secret-free operational metadata:

- detection timestamp;
- workflow run link;
- workflow event;
- Git ref;
- commit SHA;
- run attempt.

Provider credentials, raw exception payloads, evidence bytes, private object keys, database URLs, API keys, and storage keys are never copied into the issue body.

## Permission isolation

The source-processing job remains `contents: read` only.

Only the separate failure-alert job receives `issues: write`, and that job has no cloud provider secrets in its environment. This avoids expanding the permissions of the ingestion job merely to support alerts.

## Recovery policy

An alert is informational and does not perform automatic repair, retry, source bypass, cadence increase, evidence deletion, trust promotion, or capacity override. The operator must inspect the failed workflow and preserve the fail-closed state until the underlying condition is understood.

## Cost

This uses GitHub Actions and Issues already associated with the private repository. No paid notification provider or new infrastructure is introduced.
