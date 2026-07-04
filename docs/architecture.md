# Architecture

## Overview

Vexilla is a single-device, local-only system with five cooperating components, all
running on the user's Linux machine. There is no server, no cloud, and no account.

```
                         ┌────────────────────────────────────────────┐
                         │                  DEVICE                      │
                         │                                              │
  network sockets ──────▶│  ┌────────────────────┐                     │
  /proc, conntrack       │  │   COLLECTOR         │  writes flows       │
  DNS packets (port 53) ─▶│  │   (daemon)         │────────┐            │
                         │  └────────────────────┘         ▼            │
                         │                          ┌──────────────┐    │
                         │  ┌────────────────────┐  │   STORE      │    │
                         │  │  KNOWLEDGE BASE     │  │  (SQLite)    │    │
                         │  │  data/kb.db (RO)    │  └──────────────┘    │
                         │  └─────────┬──────────┘         ▲            │
                         │            │ enriches           │ reads      │
                         │            ▼                     │            │
                         │  ┌────────────────────┐         │            │
                         │  │  INSIGHT ENGINE     │─────────┘            │
                         │  │  heuristics + text  │  writes insights     │
                         │  └─────────┬──────────┘                       │
                         │            │ serves                           │
                         │      ┌─────┴──────┐                           │
                         │      ▼            ▼                           │
                         │  ┌────────┐   ┌────────┐                      │
                         │  │  API   │   │  CLI   │                      │
                         │  │ +Web UI│   │        │                      │
                         │  └────────┘   └────────┘                      │
                         └────────────────────────────────────────────┘
                          bind 127.0.0.1 only     terminal
```

## Components

### 1. Collector (`src/vexilla/collector/`)
A long-running daemon that observes network activity and writes normalized **flow
records** to the store. Two capture concerns:

- **Connection + attribution + bytes** — which process is talking to which remote
  endpoint and how much data. MVP uses `/proc/net/{tcp,tcp6,udp,udp6}` + socket→PID
  mapping via `/proc/<pid>/fd`, plus conntrack byte counters. eBPF (`bcc`/`bpftrace`)
  is an optional enhanced path for accurate per-PID byte accounting.
- **DNS mapping** — a passive AF_PACKET sniffer on port 53 parses DNS responses to
  build an `IP → domain` cache used to name remote endpoints.

Details: `collector-design.md`. The collector performs **no enrichment and no
judgment** — it only records facts.

### 2. Store (`src/vexilla/store/`)
A single local SQLite database. Holds flows, per-app/per-domain aggregates, the DNS
cache, generated insights, and settings. Stdlib `sqlite3`, WAL mode. Schema is the
contract between components — see `data-model.md`. Includes retention/pruning.

### 3. Knowledge base (`data/kb.db`, loader in `src/vexilla/kb/`)
A **read-only, shipped** SQLite database mapping domains → owner, category, plain-
language purpose, privacy note, and suggestion. Built **offline** (LLM-assisted) and
bundled with the app. No runtime network calls. Format + build: `knowledge-base.md`.

### 4. Insight engine (`src/vexilla/insight/`)
Reads flows from the store, joins with the knowledge base, applies **deterministic
heuristics** to flag unusual behavior, and generates **plain-language** summaries and
suggestions. Writes insight rows back to the store. This is Vexilla's core value.
Rules: `insight-engine.md`.

### 5. Presentation (`src/vexilla/api/`, `web/`, `cli/`)
- **API + Web UI** — FastAPI serving Jinja2 templates with HTMX for interactivity.
  Binds to `127.0.0.1:8787`. Read-only views over the store.
- **CLI** — Typer app (`vexilla today|apps|domains|status|serve`) for terminal users.

## Data flow (one cycle)

1. Collector polls sockets/conntrack (default every 2 s) and captures DNS responses.
2. It resolves endpoints via the DNS cache and writes/updates **flow** + **aggregate** rows.
3. On a schedule (default every 60 s + on demand), the insight engine:
   a. reads recent flows/aggregates,
   b. enriches domains from `kb.db`,
   c. evaluates heuristics → writes **insight** rows,
   d. regenerates the current plain-language **summary**.
4. The API/CLI read the store and render. No component blocks another; they
   communicate only through SQLite.

## Process & deployment model

- One **systemd service** runs the collector + insight engine + API in a single
  supervised process (simplest install; can split later).
- The database lives under a fixed path (e.g. `/var/lib/vexilla/vexilla.db`);
  the KB ships read-only with the package.
- Privileges: only the collector needs `CAP_NET_RAW`/`CAP_NET_ADMIN`. The web layer
  needs none and binds to loopback.

## Key design choices (see `adr/`)

- Components integrate **only through SQLite** — no IPC, no message bus. Simple,
  debuggable, crash-safe.
- Capture is **poll-based first**, eBPF second — works everywhere, optimizes later.
- **No blocking path** exists in the code — observe-only is structural, not a config flag.
- Enrichment is **fully offline** — the KB is data, not a service.

## Module boundaries (import rules)

```
collector ──▶ store            insight ──▶ store, kb
api/cli   ──▶ store, insight    kb ──▶ (self, reads data/kb.db)
```
`collector` must not import `insight`/`api`. `store` imports nothing from siblings.
This keeps the daemon lean and the layers testable in isolation.
