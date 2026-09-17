# Claim Metadata Noise Hardening

## Purpose

This post-roadmap quality hardening narrows the structured-claim candidate set by rejecting additional obvious page/contact/administrative labels before they can become new candidate claims.

The change is deliberately conservative and non-destructive. Exact source bytes, extracted text, document rows, historical claims, B2 objects, and Qdrant points are not deleted or rewritten.

## Newly rejected metadata labels

The quality floor now recognizes exact normalized labels for common non-financial metadata such as email, fax, telephone, website, page/serial numbering, time, last-updated markers, GSTIN, and toll-free contact fields. A narrowly anchored pattern also catches page/serial labels that include punctuation or a numeric suffix after extraction.

The rule does not use generic substring rejection. For example, financial labels such as `Time Deposit Rate`, `GST Collections`, or `Page Industries Revenue` remain eligible for normal downstream checks.

## Safety

- No historical evidence is removed.
- No existing claim state is changed.
- No trust event is created.
- No source or scheduler behavior changes.
- No fuzzy financial-fact extraction is introduced.
- Only derived structured candidates matching known metadata shapes are rejected.

## Validation

Regression tests cover exact metadata labels, page/serial suffix forms, and legitimate financial labels that contain similar words but must remain allowed.
