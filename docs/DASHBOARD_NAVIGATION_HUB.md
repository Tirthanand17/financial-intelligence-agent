# Dashboard Navigation Hub

## Purpose

The navigation hub gives the private operator one read-only entry point for the Financial Intelligence Agent dashboard surfaces.

Route: `GET /dashboard/hub`

The hub links to:

- Operational Dashboard
- Operational Readiness
- Intelligence Evidence View
- Claim Verification Workbench
- Evidence Timeline Explorer

## Safety boundary

The hub contains navigation only. It exposes no ingestion, scheduler, repair, deletion, trust-promotion, or other write controls. It reuses the existing dashboard HTTP Basic authentication and browser security-header middleware, including `Cache-Control: no-store`.

This page does not change the meaning or authorization model of any linked page; it only consolidates access to the existing protected read-only surfaces.
