# Vexilla

**See what your device is really talking to — in plain English.**

Vexilla is a lightweight, privacy-first Linux agent that answers one simple question:

> *"What is my laptop talking to right now, and should I care?"*

It watches which applications use the internet, which external services and domains
they connect to, how much data they consume, and whether that behavior is normal —
then explains it all in **plain human language**, not technical logs.

Vexilla is **not** an antivirus and **not** a firewall. It is a **digital transparency
companion** for normal people.

---

## What it does

- 🔎 **Which apps use the internet** — per-application network activity
- 🌐 **Which services they contact** — external domains, resolved and named
- 📊 **How much data each one uses** — per app, per domain, over time
- 🌙 **Background vs active usage** — what talks when you're not looking
- ⚠️ **Unusual behavior detection** — new domains, trackers, beaconing, data spikes
- 🗣️ **Plain-language explanations** — "Firefox contacted a Google ad tracker 40× in the background today"
- 💡 **Actionable suggestions** — reduce data use, improve privacy, improve performance

## What it does NOT do (by design)

- ❌ No TLS/HTTPS interception (we never decrypt your traffic — see [privacy.md](docs/privacy.md))
- ❌ No blocking or firewalling in the MVP (observe-only — see [roadmap.md](docs/roadmap.md))
- ❌ No data leaves your device by default (local-first — see [privacy.md](docs/privacy.md))
- ❌ No cloud account required, no telemetry, no tracking

---

## Design principles

1. **Simplicity first** — 1–2 step install, zero configuration, no security expertise required.
2. **Privacy-first** — everything runs and stays on the device by default.
3. **Human-readable** — technical data is always translated into plain language.
4. **Explainable, not magic** — detection uses transparent rules, not opaque AI.
5. **Reuse, don't reinvent** — proven capture techniques + public intel lists; our value is the insight layer.

---

## Architecture at a glance

```
┌─────────────────────────────────────────────────────────────┐
│  DEVICE (Linux) — everything below runs locally               │
│                                                               │
│  ┌───────────┐   ┌───────────┐   ┌──────────────┐            │
│  │ Collector │──▶│  SQLite   │◀──│  Insight     │            │
│  │ (daemon)  │   │  store    │   │  Engine      │            │
│  └───────────┘   └───────────┘   └──────────────┘            │
│    proc/eBPF        local DB        heuristics +             │
│    + DNS capture                    plain-language           │
│                          ▲                 │                 │
│                          │                 ▼                 │
│                  ┌───────────────┐   ┌──────────────┐        │
│                  │ Offline KB    │   │  Web UI +    │        │
│                  │ (domain facts)│   │  CLI         │        │
│                  └───────────────┘   └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

See [docs/architecture.md](docs/architecture.md) for the full design.

---

## Quick start (target experience)

```bash
# 1. install
curl -fsSL https://get.vexilla.dev/install.sh | sh    # or: pipx install vexilla

# 2. that's it — the daemon starts and the dashboard is live
xdg-open http://localhost:8787
```

CLI:

```bash
vexilla today          # plain-language summary of today's activity
vexilla apps           # top apps by data / connections
vexilla domains        # top domains contacted
vexilla status         # is the daemon healthy?
```

---

## Tech stack

- **Language:** Python 3.11+
- **Collector:** `/proc/net` + conntrack polling (MVP), eBPF (`bcc`/`bpftrace`) for enhanced accuracy
- **DNS mapping:** passive DNS capture via AF_PACKET raw socket
- **Store:** SQLite (stdlib `sqlite3`)
- **API/UI:** FastAPI + Jinja2 + HTMX (no SPA)
- **CLI:** Typer
- **License:** MIT

See [docs/tech-stack.md](docs/tech-stack.md) for rationale.

---

## Documentation index

| Document | Purpose |
|---|---|
| [docs/requirements.md](docs/requirements.md) | Functional & non-functional requirements |
| [docs/architecture.md](docs/architecture.md) | System components, data flow, module layout |
| [docs/ui-wireframes.md](docs/ui-wireframes.md) | Dashboard screen wireframes + data mapping |
| [docs/tech-stack.md](docs/tech-stack.md) | Chosen technologies and rationale |
| [docs/data-model.md](docs/data-model.md) | SQLite schema (DDL) |
| [docs/collector-design.md](docs/collector-design.md) | Network + DNS capture design |
| [docs/insight-engine.md](docs/insight-engine.md) | Detection heuristics + plain-language rules |
| [docs/knowledge-base.md](docs/knowledge-base.md) | Offline domain knowledge base: format + build |
| [docs/privacy.md](docs/privacy.md) | Privacy guarantees, consent, data handling |
| [docs/mvp-scope.md](docs/mvp-scope.md) | 2–4 week MVP plan, in/out of scope |
| [docs/roadmap.md](docs/roadmap.md) | Phased plan beyond MVP |
| [docs/adr/](docs/adr/) | Architecture Decision Records |

> **For AI agents:** start with [CLAUDE.md](CLAUDE.md), then [docs/mvp-scope.md](docs/mvp-scope.md).
