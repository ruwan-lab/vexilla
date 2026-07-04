# Offline domain knowledge base (KB)

The KB is what makes Vexilla speak human. It is a **read-only SQLite file (`kb.db`)
shipped with the app**, mapping domains to plain-language facts. It is built **offline**
(LLM-assisted) and contains **no user data**. At runtime there are **zero network calls
and zero LLM calls** (ADR-0003).

## Why this design

- **Privacy:** the user's domains are never sent anywhere; lookups are local.
- **Speed:** a local SQLite lookup is instant.
- **Determinism:** the same domain always gets the same explanation; reviewable.
- **Simplicity:** the KB is just data, versioned and shipped with releases.

## KB schema (`kb.db`)

```sql
CREATE TABLE kb_domain (
    domain         TEXT PRIMARY KEY,       -- registrable domain, e.g. "doubleclick.net"
    owner          TEXT,                   -- "Google LLC"
    category       TEXT NOT NULL,          -- see categories in insight-engine.md
    purpose_plain  TEXT NOT NULL,          -- one plain sentence: what it's for
    privacy_note   TEXT,                   -- plain sentence on privacy impact, nullable
    suggestion     TEXT,                   -- plain, safe, optional action
    confidence     TEXT NOT NULL,          -- 'high' | 'medium' | 'low'
    source         TEXT NOT NULL,          -- 'curated' | 'list' | 'llm'
    updated_at     INTEGER NOT NULL
);
CREATE INDEX idx_kb_category ON kb_domain(category);

-- Optional: known aliases / subdomains that roll up to a registrable domain.
CREATE TABLE kb_alias (
    alias   TEXT PRIMARY KEY,              -- "ssl.google-analytics.com"
    domain  TEXT NOT NULL REFERENCES kb_domain(domain)
);

CREATE TABLE kb_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- e.g. version, build_date, entry_count, list_sources
```

Lookup rule at runtime: exact domain → alias table → registrable-domain fallback
(strip subdomain) → public list category → `unrecognized`.

## Content guidelines

- **`purpose_plain`**: one sentence, no jargon. *"Serves video ads and tracks which
  ads you see."* not *"RTB ad exchange endpoint."*
- **`privacy_note`**: only when meaningful; factual, not fear-mongering.
- **`suggestion`**: safe and optional; never system-breaking.
- Prefer **registrable domains**; use `kb_alias` for common noisy subdomains.
- Mark `confidence` honestly; low-confidence entries get softer UI treatment.

## Build pipeline (offline, `src/vexilla/kb/build/`)

Run by maintainers, not users. Produces `data/kb.db` for bundling.

1. **Seed domain list** — union of:
   - top public domain lists (e.g. Tranco) for coverage of common services,
   - public tracker/ad host lists (StevenBlack, EasyList-derived, Portmaster intel) —
     these also directly set category for `advertising`/`tracker_analytics`.
   Track each list's **license** in `kb_meta.list_sources`.
2. **Deduplicate & normalize** to registrable domains; collect noisy subdomains as aliases.
3. **Categorize** — deterministic from lists first (a domain on a tracker list →
   `tracker_analytics`); remainder categorized in the next step.
4. **LLM enrichment (batch, offline)** — for the top N domains without a confident
   category, prompt an LLM to produce `owner`, `category`, `purpose_plain`,
   `privacy_note`, `suggestion`, `confidence`. Constrain output to the schema
   (structured/JSON). **This is the only place an LLM is used.**
5. **Human review** — at minimum spot-check high-traffic + low-confidence entries;
   correct and mark `source='curated'`.
6. **Emit `kb.db`** — write SQLite, set `kb_meta` (version, build_date, entry_count,
   list_sources), and record the schema version.

### Suggested target size
- MVP: **top ~10k domains** covers the large majority of real-world traffic for typical
  users. Grow toward ~50k over time. Unknown domains degrade gracefully.

## Update & distribution

- The KB ships **with the app version** (in-package, `/usr/share/vexilla/kb.db`).
- KB updates ride app updates in the MVP (no live KB fetch — preserves offline/privacy).
- A future opt-in "KB refresh" download is possible but out of MVP scope (roadmap).

## Licensing note

Only use host/domain lists whose licenses permit redistribution; record them in
`kb_meta.list_sources` and in the repo's `THIRD_PARTY.md`. This keeps Vexilla MIT-clean
(ADR-0005): we ship *data derived from permissively-licensed lists*, not GPL code.

## Acceptance checks

- `doubleclick.net` resolves to category `advertising`, an owner, a plain purpose, and a
  suggestion, `source` reflecting list/curation.
- A subdomain like `stats.g.doubleclick.net` resolves via alias/registrable fallback.
- A domain absent from the KB returns `unrecognized` without error and without alarm.
