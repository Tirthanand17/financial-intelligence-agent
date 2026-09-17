# Post-Roadmap Dashboard Security Hardening

## Purpose

This milestone strengthens the browser-facing dashboard without changing its authentication model, data model, ingestion behavior, scheduler, or trust policy.

The dashboard remains read-only and protected by the existing HTTP Basic credentials supplied through deployment secrets.

## Added response protections

All application responses receive conservative baseline browser headers:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- a restrictive `Permissions-Policy`
- one-year `Strict-Transport-Security`

All `/dashboard...` responses additionally receive:

- `Cache-Control: no-store, max-age=0`
- `Pragma: no-cache`
- `Content-Security-Policy`
- `Cross-Origin-Opener-Policy: same-origin`
- `Cross-Origin-Resource-Policy: same-origin`

These directives are applied to successful pages, JSON dashboard responses, and authentication failures so protected operational information is not intentionally cached by the application.

## Content Security Policy

The dashboard policy restricts content to the same application origin, blocks objects and framing, disallows form submission, and restricts browser capabilities. The current dashboard embeds its small CSS and JavaScript directly in the HTML, so `style-src` and `script-src` temporarily allow inline content.

A future hardening milestone can move those assets into static files and remove the inline exceptions or replace them with nonces/hashes.

## Boundaries

This change does not:

- add or expose passwords, provider credentials, connection strings, or tokens;
- change dashboard credentials;
- create a login/session database;
- add write controls;
- change ingestion or scheduler cadence;
- enable trust promotion;
- alter PostgreSQL, Qdrant, or Backblaze B2 data;
- delete evidence/history; or
- generate financial recommendations or trading actions.

## Validation

Regression tests confirm that:

- authenticated dashboard HTML receives the expected security headers;
- protected JSON responses are no-store;
- unauthenticated `401` dashboard responses are also no-store and frame-protected;
- baseline API routes receive the global safety headers; and
- dashboard-specific CSP/cache directives do not unnecessarily apply to the ordinary `/health` API route.

## Future authentication boundary

HTTP Basic over HTTPS is acceptable for the current private operator dashboard, but a future authentication change should be a separate milestone. Session login, identity-proxy integration, rate limiting, multi-user authorization, write controls, or administrative actions require dedicated threat modeling and regression testing rather than being mixed into this header-only change.
