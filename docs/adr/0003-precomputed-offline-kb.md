# ADR-0003: Plain-language via a precomputed offline knowledge base

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

The product's core value is translating technical network data into plain language.
Options for generating that text:
1. **Runtime cloud LLM** — flexible, but sending a user's domains to a third party *is*
   leaking their browsing history; contradicts privacy-first.
2. **Local small model** — private, but heavy install + resource use; fights the
   "lightweight, zero-config" goal.
3. **Precomputed offline knowledge base** — author explanations for the top domains once
   (LLM-assisted, offline), ship as data; look up locally at runtime.

## Decision

Use option 3. Ship a read-only `kb.db` of domain → plain-language facts. The LLM is used
**only at build time** to author KB entries. **No runtime LLM calls, no network calls**
for enrichment. Insight text is composed from KB entries + deterministic templates.

## Consequences

- Fully private, instant, deterministic, reviewable explanations.
- No per-user inference cost or dependency on an external service.
- Coverage is bounded by the KB; unknown domains degrade to "unrecognized" gracefully.
- KB must be maintained and shipped with releases; updates ride app updates in the MVP.
- Optional local-model summaries and opt-in KB refresh are possible later (roadmap).
