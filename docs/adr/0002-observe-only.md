# ADR-0002: Observe-only in the MVP (no blocking)

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

Tools like Portmaster and OpenSnitch both observe and block traffic. Blocking adds:
traffic-control machinery (nfqueue/eBPF drop), fail-safe design (a bug can cut the
user's network), a decision UI, and higher trust/risk. Vexilla's stated identity is
"digital transparency," and its top constraint is simplicity.

## Decision

The MVP **observes only**. There is **no code path that drops, delays, or alters
traffic**. Observe-only is structural, not a config toggle.

## Consequences

- Dramatically simpler, lower-risk, faster to build.
- True to the "transparency companion, not a firewall" positioning.
- Users can't act *through* Vexilla in the MVP — suggestions point them to external
  actions (browser extensions, DNS blocklists, app settings).
- Adding blocking later is a significant shift requiring an ADR that supersedes this one
  (see roadmap Phase C).
