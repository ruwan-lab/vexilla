# MVP scope & build plan

Target: a working, useful **Linux, observe-only** MVP buildable by one technical
founder in **2–4 weeks**. Prioritize a thin end-to-end slice over breadth.

## In scope (MVP)

- Poll-based collector (`/proc` + conntrack) with process→connection→bytes attribution.
- Passive DNS capture → `IP → domain` naming.
- Active vs background classification (pragmatic heuristic).
- SQLite store + hourly aggregation + retention/pruning.
- Offline KB (`kb.db`) with ~10k domains; enrichment at read time.
- Insight engine: `new_domain`, `tracker`, `background_spike`, `beaconing`,
  `heavy_background_app`, `unnamed_endpoint_volume`.
- Plain-language daily summary + per-insight text + suggestions.
- Local web dashboard (FastAPI + Jinja2 + HTMX), loopback-only.
- CLI: `today`, `apps`, `domains`, `status`, `serve`, `reset`.
- systemd service + `install.sh`/`pipx` install + consent screen.

## Explicitly out of scope (MVP)

Blocking/firewalling · eBPF-required features (eBPF is optional enhancement only) ·
mobile · macOS/Windows · cloud/sync/accounts · runtime LLM · live KB updates ·
TLS inspection · multi-user. (See `roadmap.md`.)

## Phased plan

### Phase 0 — Skeleton (days 1–2)
- Repo layout per `CLAUDE.md`; package scaffolding; config with defaults.
- Create runtime DB from `data-model.md`; migrations shell; `schema_meta`.
- `vexilla status` returns healthy; empty dashboard renders.
- **Acceptance:** service starts, DB created, dashboard loads on `127.0.0.1:8787`.

### Phase 1 — Collector core (days 3–7)
- `/proc/net` parsing + inode→PID→app resolution → `app`, `endpoint`, `flow` rows.
- conntrack byte accounting matched by 5-tuple.
- Passive DNS capture → `dns_cache`; endpoint naming.
- Active/background classification.
- **Acceptance:** the collector-design.md acceptance checks pass; real flows appear in DB
  with names and byte counts.

### Phase 2 — Store aggregation & retention (days 6–8, overlaps)
- Hourly rollup into `agg_hourly`; daily prune job at `retention_days`.
- **Acceptance:** dashboard reads only aggregates; old data prunes.

### Phase 3 — Knowledge base (days 5–10, parallelizable)
- Build pipeline (`knowledge-base.md`): seed lists → categorize → LLM enrich → review →
  emit `kb.db` (~10k domains). Ship in package.
- KB loader with alias/registrable/list/unknown fallback.
- **Acceptance:** knowledge-base.md acceptance checks pass.

### Phase 4 — Insight engine (days 9–14)
- Enrichment join + the six heuristics + templates + suggestion catalog.
- Daily summary generation cached in `summary`.
- **Acceptance:** insight-engine.md acceptance checks pass; summary reads naturally.

### Phase 5 — Presentation (days 12–18)
- Dashboard: today's summary, top apps, top domains, timeline, flagged items, per-item
  plain-language explanations, dismiss.
- CLI commands wired to the same store/insight layer.
- **Acceptance:** FR-12/FR-13/FR-14 satisfied; non-technical reader understands every screen.

### Phase 6 — Packaging & polish (days 16–21)
- systemd unit with ambient capabilities; `install.sh`/`pipx`; consent screen; uninstall.
- README quick-start works end to end on a clean Ubuntu + Fedora VM.
- **Acceptance:** 1–2 step install (NFR-6); NFR-9/10/11 within budget.

> Phases overlap (KB build can run alongside collector work). A solo founder can hit a
> usable MVP by end of week 3, with week 4 for polish/testing on real distros.

## Definition of done (MVP)

- Fresh install on Ubuntu and Fedora → dashboard shows real, named, plain-language
  network activity within minutes, with at least the six insight types firing on
  realistic usage.
- All NFRs met; all `docs/*` acceptance checks pass.
- No user data leaves the device; consent screen present; uninstall clean.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Byte attribution imprecise without eBPF | Ship poll+conntrack MVP; mark data source in evidence; add eBPF path as enhancement. |
| Encrypted DNS (DoH) hides names | Document limitation; reverse-DNS fallback; still show IP + volume. |
| KB coverage gaps | Graceful `unrecognized`; grow KB over time; lists cover trackers well. |
| Background/foreground detection weak headless | Pragmatic heuristic + record which branch fired; refine post-MVP. |
| Distro/kernel variance | Poll path works broadly; test on Ubuntu+Fedora+Arch; degrade gracefully. |
