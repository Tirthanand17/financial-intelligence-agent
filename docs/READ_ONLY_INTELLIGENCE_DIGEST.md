# Read-Only Intelligence Digest

## Purpose

The Intelligence Digest is a protected, deterministic summary of already-persisted financial/economic evidence. It is intended to provide a concise daily/weekly-style review without introducing generated facts, forecasts, or trading advice.

## Routes

- `GET /dashboard/digest` — authenticated human-readable digest.
- `GET /dashboard/digest/status` — authenticated JSON snapshot used by the dashboard.

The routes reuse the existing dashboard HTTP Basic authentication, no-store policy, security headers, and request correlation middleware.

## Digest inputs

The digest reads only persisted project state:

- indexed documents;
- quality-safe active structured claims;
- persisted dated evidence changes from the existing change-detection service;
- persisted conflicted claims;
- deterministic operator incidents from the existing readiness/incident layer.

The lookback window is bounded to 1–30 days and returned items are bounded to 1–50 per section.

## Temporal policy

Claims enter the selected window only when they have an explicit persisted effective date or publication date. Missing dates remain missing and are not replaced with retrieval time.

Documents are selected by their persisted retrieval timestamp because that field describes when evidence entered the system; it is not presented as the document's publication date.

## Safety boundaries

The digest:

- performs no external source fetch;
- invokes no language model;
- performs no ingestion;
- performs no claim-state transition;
- creates no verification or trust event;
- does not enable trust promotion;
- does not modify the scheduler;
- does not delete or rewrite evidence;
- does not send external notifications;
- does not forecast market direction;
- does not generate trading signals or recommendations.

## Scheduling status

This milestone builds the digest content and protected dashboard surface only. Automatic external delivery is intentionally not configured because no delivery channel/recipient has been explicitly approved. The existing production ingestion schedule is not modified.

A future scheduling decision may generate a private digest artifact or deliver the digest through an explicitly approved channel after the current scheduler observation period is reviewed. That decision should not weaken any ingestion, evidence, trust, capacity, or reconciliation control.

## Validation

Regression coverage verifies bounded lookback/limit behavior, explicit temporal handling, no invented dates, no state mutation, no language-model invocation, authentication, no-store behavior, absence of write controls, and inclusion in the production smoke contract.
