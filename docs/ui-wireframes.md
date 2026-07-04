# Dashboard wireframes

Low-fidelity wireframes for the Vexilla local web UI. These describe **layout, content,
copy tone, data sources, and interactions** — not visual styling. They are the contract
for the `api/` + `web/` layer (FastAPI + Jinja2 + HTMX, server-rendered, loopback-only).

## Principles (apply to every screen)

- **Plain language first.** Every technical value has a human sentence next to it (FR-14).
  Numbers support the words; they never stand alone.
- **Calm, not alarmist.** Severity ceiling is `warning` (ADR/insight-engine). No red
  "CRITICAL" theatrics. Trackers are "worth knowing," not "threats."
- **Read-only.** The UI never changes traffic (observe-only). The only writes are UX
  state: dismiss an insight, change a setting, trigger export/reset.
- **HTMX, no SPA.** Server renders full pages; HTMX swaps fragments for filters, tab
  switches, dismiss, and the auto-refreshing "live" areas. Everything degrades to a
  working page without JS.
- **Data sources are named** per element as `[table.field]` referring to `data-model.md`.
- **Units:** show human units ("2.3 MB", "40 times", "2:15 PM"). Bind: `127.0.0.1:8787`.

## Global layout (shell)

```
┌───────────────────────────────────────────────────────────────────────────┐
│  🚩 Vexilla        Today   Apps   Services   Timeline   Flags(3)   ⚙        │  ← top nav
├───────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                            << page content >>                               │
│                                                                             │
├───────────────────────────────────────────────────────────────────────────┤
│  🔒 Everything stays on this device. Vexilla never decrypts your traffic.   │  ← persistent footer
└───────────────────────────────────────────────────────────────────────────┘
```

- Nav item **Flags(3)** shows the count of un-dismissed insights `[insight WHERE dismissed=0]`.
- Footer is a permanent privacy reassurance (reinforces `privacy.md`).
- Active nav item highlighted. Nav is the only chrome; keep it minimal.

---

## Screen 0 — First-run consent (blocking, shown once)

Required by NFR-3 / `privacy.md`. Capture does **not** begin until acknowledged.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  🚩  Welcome to Vexilla                                                      │
│                                                                             │
│  Vexilla shows you what your device talks to on the internet — in plain      │
│  language. Before it starts, here's exactly what it does.                    │
│                                                                             │
│   Vexilla WILL see            │   Vexilla will NEVER                         │
│   ─────────────────────────   │   ────────────────────────────             │
│   • which apps go online      │   • decrypt your traffic                    │
│   • which services/domains    │   • read your messages or pages            │
│   • how much data they use    │   • send your data anywhere                │
│   • when (active/background)  │   • require an account                     │
│                                                                             │
│  • Everything is stored only on this device (default: last 30 days).        │
│  • You can pause monitoring or uninstall at any time.                       │
│                                                                             │
│                   [ Read the details ]   [  Start monitoring  ]             │
└───────────────────────────────────────────────────────────────────────────┘
```

- "Start monitoring" writes a `setting` consent flag + timestamp, then redirects to Today.
- "Read the details" expands the full `privacy.md` summary inline (HTMX fragment).
- No pre-checked boxes, no dark patterns.

---

## Screen 1 — Today (home / default)

The signature screen: a plain-language day summary on top, evidence below.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Today · Thursday, Jul 3                                    [ ⟳ live ]      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  Today your device talked to 42 services across 11 apps, using        │  │
│  │  318 MB (76 MB in the background). The biggest talker was Firefox.     │  │  ← [summary.text]
│  │  9 tracking or ad services were contacted. 2 things are worth a look.  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│   ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│   │  318 MB   │  │   76 MB   │  │    42     │  │     9     │              │  ← stat tiles
│   │ total data│  │ background│  │ services  │  │ trackers  │              │    [summary.stats_json]
│   └───────────┘  └───────────┘  └───────────┘  └───────────┘              │
│                                                                             │
│  Worth a look                                                    See all →  │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ ⚠  Slack used 142 MB in the background — about 6× its usual.          │  │  ← top insights
│  │    You can quit Slack when you're not using it to save data.  [dismiss]│  │    [insight ORDER BY
│  │ ⚑  Firefox contacted a new ad service: doubleclick.net (Google).      │  │     severity, created_at
│  │    Used for serving and measuring ads.                       [dismiss]│  │     WHERE dismissed=0 LIMIT 3]
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Top apps today                              Top services today            │
│  ┌───────────────────────────┐              ┌────────────────────────────┐ │
│  │ Firefox        128 MB  ███ │              │ googlevideo.com    64 MB ██│ │  ← [agg_hourly rollup
│  │ Slack          142 MB  ███ │              │ slack.com          58 MB ██│ │     by app / endpoint
│  │ Spotify         31 MB  █   │              │ doubleclick.net     3 MB · │ │     for today]
│  │ apt (updates)   18 MB  ·   │              │ 1.2.3.4 (unknown)  12 MB · │ │
│  │                 See all →  │              │              See all →     │ │
│  └───────────────────────────┘              └────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────┘
```

- **[⟳ live]** toggles HTMX polling (e.g. `hx-trigger="every 10s"`) that refreshes the
  stat tiles + top lists fragment. Off = static snapshot.
- Each **insight row** shows `title` + `body` + `suggestion`; `[dismiss]` is an HTMX
  POST that sets `insight.dismissed=1` and removes the row.
- Bars are relative-width (share of the day's bytes); label always carries the number.
- App/service rows link to their detail screens. Unknown endpoints show the IP + a plain
  "(unknown service)" label `[endpoint.domain IS NULL]`.
- Icon key: ⚠ = `warning`, ⚑ = `notice`, ℹ = `info`.

---

## Screen 2 — Apps (list) & App detail

**List:**

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Apps                          Range: [ Today ▾ ]   Sort: [ Data used ▾ ]   │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ App          Data ↓     Background   Services   Last active           │  │
│  │ ─────────────────────────────────────────────────────────────────── │  │
│  │ Slack        142 MB     138 MB (97%)   4        2 min ago      →      │  │  ← [app joined with
│  │ Firefox      128 MB      12 MB (9%)    31        now           →      │  │     agg_hourly over range]
│  │ Spotify       31 MB       2 MB (6%)     6        14 min ago    →      │  │
│  │ apt           18 MB      18 MB (100%)   2        1 hr ago      →      │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

- Range selector (`Today / 7 days / 30 days`) and Sort are HTMX fragment swaps.
- "Background %" makes the active/background split legible at a glance `[agg_hourly.bg_bytes]`.

**App detail (click a row):**

```
┌───────────────────────────────────────────────────────────────────────────┐
│  ← Apps   /   Slack                                                          │
│                                                                             │
│  In plain terms: Slack is a messaging app. Today it used 142 MB, almost     │  ← composed sentence
│  all of it in the background — it keeps syncing even when you're not         │    (template + numbers)
│  looking. If you don't need it running, quitting it will save data.          │
│                                                                             │
│   142 MB total   ·   138 MB background   ·   4 services   ·  path: /usr/…    │  [app.exe_path]
│                                                                             │
│  Data over the day                                                          │
│  ▁▁▂▃▇█▆▄▂▁▁▂  (hourly)                                                      │  ← [agg_hourly sparkline]
│                                                                             │
│  Services this app talked to                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ slack.com            132 MB    messaging        essential            │  │  ← [endpoints for this app
│  │ slack-edge.com         6 MB    file/content     cdn                  │  │     + kb category]
│  │ doubleclick.net        1 MB    ads/tracking     advertising   ⚑     │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  Flags for this app:  1 background-usage notice                    See →   │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Screen 3 — Services (domains) list & Service detail

**List** mirrors Apps but keyed by endpoint/domain, with a **category filter**:

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Services            Range:[ Today ▾ ]   Show:[ All ▾ ]   [ ⚑ trackers only]│
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ Service            Owner        Category      Data ↓   Apps           │  │
│  │ ─────────────────────────────────────────────────────────────────── │  │
│  │ googlevideo.com    Google       media         64 MB    Firefox    →   │  │  ← [endpoint + kb_domain
│  │ slack.com          Salesforce   messaging     132 MB   Slack      →   │  │     + agg over range]
│  │ doubleclick.net    Google       advertising ⚑  3 MB    Firefox,…  →   │  │
│  │ 1.2.3.4 (unknown)  —            unrecognized  12 MB    Spotify    →   │  │  ← NULL-domain fallback
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

**Service detail:**

```
┌───────────────────────────────────────────────────────────────────────────┐
│  ← Services   /   doubleclick.net                                    ⚑ ad   │
│                                                                             │
│  What is this?  doubleclick.net is run by Google. It serves ads and         │  ← [kb_domain.purpose_plain]
│  measures which ads you see across websites.                                 │
│                                                                             │
│  Privacy note:  This is an advertising/tracking service. It can help build   │  ← [kb_domain.privacy_note]
│  a profile of your browsing.                                                 │
│                                                                             │
│  What you can do:  Use a tracker-blocking browser extension or a DNS         │  ← [kb_domain.suggestion]
│  blocklist to reduce contact with services like this.                        │
│                                                                             │
│   3 MB today   ·   contacted 40 times   ·   34 in the background            │  [flow/agg evidence]
│                                                                             │
│  Apps that contacted it:   Firefox (38),  Chrome (2)                         │
│  When:  ▁▁█▁▁▁█▁▁▁█▁  (looks like a regular pattern)                         │  ← beaconing hint if flagged
│                                                                             │
│  Where the info comes from: shipped knowledge base · confidence: high        │  ← [kb_domain.source/confidence]
└───────────────────────────────────────────────────────────────────────────┘
```

- If the domain is **not** in the KB, replace the top three blocks with a neutral:
  *"We don't have details on this service yet. Here's what your device did with it."* —
  never alarming (per insight-engine `unrecognized` rule).
- Showing "where the info comes from" keeps the tool **explainable** (auditable claims).

---

## Screen 4 — Timeline

Answers "what happened when," including background activity while you were away.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Timeline · Today                       [ ● active  ○ background ]  [day ▾]  │
│                                                                             │
│  MB                                                                          │
│  80 ┤                        ██                                             │
│  60 ┤            ██          ██          ██                                 │  ← stacked hourly bars
│  40 ┤     ██     ██    ██    ██    ██    ██     ██                          │    active vs background
│  20 ┤ ██  ██  ██ ██ ██ ██ ██ ██ ██ ██ ██ ██ ██ ██ ██                       │    [agg_hourly, bg_bytes]
│   0 ┼───────────────────────────────────────────────────────────────      │
│     12a  3a   6a   9a   12p   3p   6p   9p                                   │
│                                                                             │
│  Notable moments                                                            │
│  • 2:00–3:00 AM — Slack synced 142 MB in the background.            [look →]│  ← insights placed on
│  • 9:15 AM — Firefox first contacted doubleclick.net (new).        [look →]│    the timeline by time
└───────────────────────────────────────────────────────────────────────────┘
```

- Hover/tap a bar → HTMX fragment listing that hour's top apps/services.
- "Notable moments" = insights ordered by `created_at`, each linking to detail.
- The background emphasis is the point: it surfaces "what talks when you're not looking."

---

## Screen 5 — Flags (all insights)

The full, filterable list behind the nav "Flags(N)" badge.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Flags                    Type:[ All ▾ ]   [ ✓ hide dismissed ]  [ dismiss all]│
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ ⚠  Heavy background use · Slack                             2:47 AM   │  │
│  │    Slack used 142 MB in the background — about 6× its usual.          │  │  ← [insight rows,
│  │    → You can quit Slack when not in use to save data.      [dismiss]  │  │     newest first]
│  │ ─────────────────────────────────────────────────────────────────── │  │
│  │ ⚑  New service · Firefox → doubleclick.net                  9:15 AM   │  │
│  │    A new ad/tracking service, run by Google.               [dismiss]  │  │
│  │ ─────────────────────────────────────────────────────────────────── │  │
│  │ ℹ  Unnamed service with notable data · Spotify → 1.2.3.4    1:10 PM   │  │
│  │    12 MB to a service we couldn't name (encrypted DNS).    [dismiss]  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────┘
```

- Type filter maps to `insight.kind`. Each card = `title` / `body` / `suggestion`.
- `[dismiss]` and `[dismiss all]` are HTMX POSTs updating `insight.dismissed`.
- "Why am I seeing this?" expander (HTMX) reveals `insight.evidence` numbers — keeps it
  explainable without cluttering the default view.

---

## Screen 6 — Settings

Minimal, all with sensible defaults (NFR-8). Writes to `setting`.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  Settings                                                                    │
│                                                                             │
│  Monitoring                                                                  │
│   [ ● Active ]   Pause monitoring  ▸                                         │  ← pause = collector off
│                                                                             │
│  History                                                                    │
│   Keep data for:  [ 30 days ▾ ]   ( older data is deleted automatically )   │  [setting.retention_days]
│                                                                             │
│  Your data                                                                  │
│   [ Export my data ]   [ Delete all data ]                                  │  ← export JSON/CSV; reset
│                                                                             │
│  Status                                                                     │
│   Capture method: /proc + conntrack   ·   DNS naming: on                    │  ← from `vexilla status`
│   Knowledge base: v2026.06 · 10,240 services                                │  [kb_meta]
│                                                                             │
│  About                                                                      │
│   Vexilla 0.1 · MIT · runs only on this device · no account, no telemetry.  │
└───────────────────────────────────────────────────────────────────────────┘
```

- "Delete all data" requires a confirm step; clears the runtime DB (`vexilla reset`),
  leaves the shipped KB intact.
- "Capture method" honestly reflects whether the eBPF or poll path is active.

---

## Cross-cutting states

- **Empty (fresh install):** every screen shows a friendly *"Vexilla is watching. Come
  back in a few minutes and you'll see what your device is talking to."* Never a blank table.
- **Unnamed endpoints:** always render as `IP (unknown service)` with a one-line reason
  ("often caused by apps using encrypted DNS") — matches `collector-design.md` limitations.
- **Loading (HTMX swaps):** inline skeleton rows, not full-page spinners.
- **No JS:** pages still render server-side; filters fall back to normal links/query params.
- **Accessibility:** never encode meaning by color alone — pair every ⚠/⚑/ℹ icon with text.

## Screen ↔ data/requirements map

| Screen | Primary tables | Key requirements |
|---|---|---|
| Consent | `setting` | NFR-3, privacy.md |
| Today | `summary`, `insight`, `agg_hourly` | FR-9, FR-10, FR-12, FR-14 |
| Apps | `app`, `agg_hourly`, `flow` | FR-1, FR-3, FR-5 |
| Services | `endpoint`, `kb_domain`, `agg_hourly` | FR-2, FR-7 |
| Timeline | `agg_hourly`, `insight` | FR-4, FR-5 |
| Flags | `insight` | FR-8, FR-10 |
| Settings | `setting`, `kb_meta` | FR-16, FR-17, NFR-1/4 |
