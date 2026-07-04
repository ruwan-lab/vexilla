# Requirements

Requirement IDs are stable references. `FR` = functional, `NFR` = non-functional.
`[MVP]` = required for first release; `[LATER]` = deferred (see `roadmap.md`).

## Functional requirements

### Data collection
- **FR-1 [MVP]** Detect active outbound network connections and attribute each to the
  originating process (name, PID, executable path).
- **FR-2 [MVP]** Resolve each remote endpoint to a domain name via passive DNS capture;
  fall back to reverse DNS, then raw IP when no name is available.
- **FR-3 [MVP]** Measure data volume (bytes sent/received) per connection, aggregated
  per app and per domain.
- **FR-4 [MVP]** Record timestamps so activity can be bucketed by time (hour/day).
- **FR-5 [MVP]** Classify each connection as **active** or **background** (see
  `insight-engine.md` for the definition).
- **FR-6 [LATER]** Attribute traffic on mobile / macOS / Windows.

### Enrichment & insight
- **FR-7 [MVP]** Enrich domains using the offline knowledge base: owner, category
  (ad/tracker/CDN/telemetry/essential/etc.), plain-language purpose, privacy note.
- **FR-8 [MVP]** Flag "unusual" behavior via transparent heuristics: new domain,
  known tracker, background data spike, regular beaconing. (See `insight-engine.md`.)
- **FR-9 [MVP]** Produce a daily plain-language summary of the device's network behavior.
- **FR-10 [MVP]** Produce actionable suggestions (reduce data, improve privacy/perf).
- **FR-11 [LATER]** Optional local small-model summaries for custom questions.

### Presentation
- **FR-12 [MVP]** Serve a local web dashboard on `localhost` showing: today's summary,
  top apps, top domains, timeline, and flagged items.
- **FR-13 [MVP]** Provide a CLI: `today`, `apps`, `domains`, `status`, `serve`.
- **FR-14 [MVP]** Every technical value shown must have a plain-language equivalent.

### Lifecycle
- **FR-15 [MVP]** Run as a background service (systemd) that starts on boot.
- **FR-16 [MVP]** Retain history for a configurable window (default 30 days) and prune
  older data automatically.
- **FR-17 [MVP]** Provide a one-command install and a clean uninstall.

## Non-functional requirements

### Privacy & security
- **NFR-1 [MVP]** No user network data leaves the device by default. No telemetry.
- **NFR-2 [MVP]** No TLS/HTTPS interception or decryption, ever.
- **NFR-3 [MVP]** Show an explicit consent screen on first run describing what is captured.
- **NFR-4 [MVP]** The dashboard binds to loopback only (`127.0.0.1`) by default.
- **NFR-5 [MVP]** The daemon requests the minimum Linux capabilities needed
  (`CAP_NET_RAW`/`CAP_NET_ADMIN`), not full root where avoidable.

### Simplicity & UX
- **NFR-6 [MVP]** Install in ≤ 2 user steps with zero required configuration.
- **NFR-7 [MVP]** No security knowledge required to understand any screen.
- **NFR-8 [MVP]** Sensible defaults for every setting.

### Performance
- **NFR-9 [MVP]** Collector CPU overhead < 3% on a typical laptop under normal load.
- **NFR-10 [MVP]** Collector steady-state memory < 150 MB.
- **NFR-11 [MVP]** Dashboard first paint < 1 s on localhost.

### Portability & footprint
- **NFR-12 [MVP]** Run on mainstream Linux distros (Ubuntu/Debian/Fedora/Arch),
  kernel ≥ 5.4. Degrade gracefully where eBPF is unavailable (fall back to `/proc`).
- **NFR-13 [MVP]** Ship as a Python package; heavy native deps optional, not required.

### Maintainability
- **NFR-14 [MVP]** Detection rules are declarative and documented in `insight-engine.md`.
- **NFR-15 [MVP]** The knowledge base is regenerable from a documented build process.

## Out of scope (MVP)

Blocking/firewalling · mobile · macOS/Windows · cloud sync · multi-device dashboard ·
user accounts · TLS inspection · deep packet inspection of payloads.
