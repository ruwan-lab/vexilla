# ADR-0006: No TLS/HTTPS interception (permanent)

- **Status:** Accepted (permanent non-goal)
- **Date:** 2026-07-03

## Context

To describe *what* a connection is doing in detail, one could MITM TLS (install a local
root CA, decrypt traffic). This would reveal full URLs and content but requires trusting
Vexilla with the user's entire encrypted traffic, weakens the device's security posture,
and is exactly the kind of invasive behavior a *transparency* tool should avoid.

Domain-level visibility is achievable **without** decryption via DNS responses and TLS
SNI/connection metadata.

## Decision

Vexilla will **never** intercept or decrypt TLS. Visibility is limited to connection
metadata (who/where/how much/when) and DNS names. This is a **permanent non-goal**.

## Consequences

- Strong, defensible trust and privacy story; nothing to misuse.
- We cannot show payload/URL-level detail — acceptable; it's not the product's purpose.
- Some endpoints stay unnamed when encrypted DNS (DoH/DoT) is used; documented as a known
  limitation with reverse-DNS fallback.
- Reversing this decision would fundamentally change the product's identity and trust
  model and must never be a silent change.
