# ADR-0004: Lean Python collector reusing techniques, not embedding OpenSnitch

- **Status:** Accepted
- **Date:** 2026-07-03

## Context

We want proven capture without re-solving a hard problem. Options:
1. **Embed/consume OpenSnitch** — its daemon is Go and GPL-3; consuming its event stream
   adds a Go runtime dependency and makes Vexilla GPL-3 (viral).
2. **Build a lean Python collector**, reusing OpenSnitch/Portmaster *techniques* and
   *public intel lists*, but writing our own capture using `/proc`+conntrack (MVP) and
   optional eBPF (`bcc`/`bpftrace`).

The founder is Python-first and values simplicity and license freedom.

## Decision

Choose option 2. Reuse the *knowledge* (how to attribute sockets to PIDs, how to capture
DNS, which host lists to use) and *permissively-licensed data*, but implement a Python
collector. Do **not** embed OpenSnitch code.

## Consequences

- No Go runtime; single-language Python stack; simpler install.
- Vexilla stays free to license permissively (see ADR-0005).
- We own and can shape the capture path (poll-first, eBPF-optional).
- We reimplement attribution ourselves — mitigated by well-understood techniques and the
  observe-only scope (no traffic-control complexity).
- Any host/domain lists we ship must be license-compatible and credited (`THIRD_PARTY.md`).
