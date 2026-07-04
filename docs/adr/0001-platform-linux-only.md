# ADR-0001: Linux-only for the MVP

- **Status:** Accepted
- **Date:** 2026-07-03
- **Deciders:** Founder (technical, Python/Linux/AWS)

## Context

Vexilla needs per-application network attribution + DNS naming. The difficulty varies
enormously by platform:
- **Linux:** clean via `/proc/net`, conntrack, and eBPF; no vendor gatekeeping.
- **macOS:** requires a NetworkExtension system extension, Apple entitlements, and
  notarization — significant friction.
- **Windows:** WFP/ETW; outside the founder's core skill set.
- **Mobile:** iOS cannot attribute traffic to specific apps at all; Android is limited
  without root.

The founder is strongest on Linux, and simplicity + speed to a usable MVP is the goal.

## Decision

Target **Linux only** for the MVP. Design the collector so the output schema is
platform-agnostic, making later platforms additive.

## Consequences

- Fastest path to a real, useful MVP; plays to founder strengths.
- Broadest and cleanest data access with least gatekeeping.
- Smaller initial audience than a cross-platform tool.
- macOS/Windows/mobile deferred to the roadmap, each as its own effort/ADR.
