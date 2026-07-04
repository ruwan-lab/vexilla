# Insight engine

This is Vexilla's core value. It turns raw flows into **plain-language understanding**
and **actionable suggestions**, using **transparent, deterministic rules** — never a
black-box model on the hot path (ADR-0003, "explainable, not magic").

Inputs: `flow`, `agg_hourly`, `endpoint`, `app` (runtime DB) + `kb.db` (knowledge base).
Outputs: `insight` rows and the daily `summary` (see `data-model.md`).

## Enrichment step (runs first)

For each endpoint domain, look up `kb.db`:
- `owner` (e.g. "Google LLC"), `category` (see list below), `purpose_plain`,
  `privacy_note`, `suggestion`.
- If the domain is unknown to the KB, derive a soft category from public host lists
  (tracker/ad lists shipped alongside the KB) and mark `kb_hit=false`. Unknown, un-listed
  domains get a neutral "unrecognized service" treatment (not alarming by default).

**Categories:** `essential`, `os_update`, `cdn`, `cloud_infra`, `advertising`,
`tracker_analytics`, `telemetry`, `social`, `media_streaming`, `messaging`,
`unrecognized`. (Kept small and human-meaningful.)

## Heuristics (the `insight.kind` values)

Each rule has: a trigger, a severity, a plain-language template, and the evidence it
records. Thresholds live in `setting` with the defaults below.

| `kind` | Trigger | Severity | Default threshold |
|---|---|---|---|
| `new_domain` | An app contacts a domain not seen for this app in the last `new_domain_days`. | `notice` | 14 days |
| `tracker` | Endpoint category ∈ {advertising, tracker_analytics}. | `notice` | — |
| `background_spike` | An app's background bytes in the last hour > `spike_factor` × its 7-day hourly background median (min floor `spike_floor_mb`). | `warning` | 5×, 20 MB |
| `beaconing` | ≥ `beacon_min_count` connections to the same domain with low inter-arrival variance (regular interval). | `notice` | 6 events, CV < 0.25 |
| `heavy_background_app` | App transferred > `heavy_bg_mb` while classified background over the day. | `warning` | 100 MB |
| `unnamed_endpoint_volume` | Significant data to an endpoint with no resolvable name. | `info` | 50 MB |

Rules are **independent and additive**. Each fires its own `insight` row; the summary
aggregates them. Add new rules by appending here + a pure function in code.

### Rule design constraints
- Every rule must be explainable to a non-technical user in **one sentence**.
- Every rule writes `evidence` (JSON: the numbers used) so the claim is auditable.
- No rule may be alarmist about `unrecognized`/`cdn`/`essential` by default.
- Severity `warning` is the ceiling in the MVP — nothing is "critical" (we're not AV).

## Plain-language generation

**Two layers, both offline/deterministic — no runtime LLM.**

1. **Domain explanations** come pre-written from `kb.db` (`purpose_plain`,
   `privacy_note`, `suggestion`). The LLM's role was to author these *at build time*
   (`knowledge-base.md`), not at runtime.

2. **Sentence templates** compose the numbers + KB text into insights and the daily
   summary. Templates are plain strings with slots. Examples:

   - `new_domain`:
     > "**{app}** contacted a new service today: **{domain}** ({owner}). It's used for
     > {purpose_plain}. {privacy_note}"
   - `tracker`:
     > "**{app}** talked to **{domain}**, a {category_human} run by {owner}, {count}
     > times{bg_clause}. {suggestion}"
   - `background_spike`:
     > "**{app}** used **{mb} MB** in the background in the last hour — about {factor}×
     > its usual. {suggestion_or_investigate}"
   - Daily summary skeleton:
     > "Today your device talked to **{domain_count} services** across **{app_count}
     > apps**, using **{total_mb} MB** ({bg_mb} MB in the background). The biggest talker
     > was **{top_app}**. {n_trackers} tracking/ad services were contacted. {headline_flags}"

Templates must degrade gracefully when a slot is missing (e.g. no owner → drop the
parenthetical). Keep a single templates module so wording is consistent and reviewable.

## Suggestion catalog

Suggestions are short, safe, and non-destructive. Sourced from the KB per-domain where
available, plus a small generic set keyed by category:
- advertising/tracker → "You can reduce this with a tracker-blocking browser extension
  or DNS blocklist."
- telemetry → "Many apps let you turn off usage/analytics reporting in their settings."
- heavy_background_app → "If you don't need {app} running in the background, you can
  quit it or disable its auto-start to save data."

Never suggest actions that could break the user's system; never auto-apply anything
(observe-only).

## Scheduling

- Enrichment + heuristics run every `insight_interval` (default 60 s) and on demand
  from the API/CLI.
- The daily `summary` is regenerated whenever underlying stats change materially and at
  least once per hour; `vexilla today` triggers a fresh render.

## Acceptance checks

- A first-ever connection to `some-ads.example` by Firefox produces both a `new_domain`
  and a `tracker` insight with correct plain-language text and a suggestion.
- Turning off the network for an app and back on with a periodic poller produces a
  `beaconing` insight only after the interval regularity threshold is met.
- The daily summary renders correctly when some endpoints are unnamed (NULL domain).
