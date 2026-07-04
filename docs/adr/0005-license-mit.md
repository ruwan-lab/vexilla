# ADR-0005: MIT license

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

Vexilla is non-commercial-first and intended to build trust through openness. Because we
reuse only *techniques* and *permissively-licensed data* (not GPL code — ADR-0004), we
are free to choose the license. Candidates: MIT (permissive) or GPL-3 (copyleft).

## Decision

License Vexilla under **MIT**.

## Consequences

- Maximum freedom for others to use/contribute; lowest friction for a community tool.
- We must ensure no GPL code is embedded and that all shipped lists/data are
  MIT-compatible and credited in `THIRD_PARTY.md` (see `knowledge-base.md`).
- If we ever embed GPL code (e.g. OpenSnitch), this ADR must be revisited — that would
  force GPL-3.
