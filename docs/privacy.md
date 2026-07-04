# Privacy & security design

Privacy is the product's foundation, not a feature. These are **guarantees**, enforced
structurally in the code — not just promises.

## Guarantees (MVP)

1. **Local-first.** All capture, storage, enrichment, and rendering happen on the
   device. No user network data leaves the machine by default. (NFR-1)
2. **No telemetry.** Vexilla itself phones no one. There is no analytics, no crash
   upload, no "anonymous usage stats" without explicit opt-in (and none in MVP).
3. **No TLS/HTTPS interception.** We never decrypt traffic. Visibility comes from DNS
   responses and connection metadata (who/where/how much), never content. (ADR-0006)
4. **No payload inspection.** We read connection 5-tuples, byte counts, and DNS names —
   not the data being transferred.
5. **Loopback-only UI.** The dashboard binds to `127.0.0.1` by default; it is not
   reachable from the network. (NFR-4)
6. **Least privilege.** Only the collector holds `CAP_NET_RAW`/`CAP_NET_ADMIN`; the rest
   runs unprivileged. No full-root requirement. (NFR-5)
7. **User owns the data.** The database is a local file the user can inspect, export, or
   delete. Uninstall removes it (with confirmation).

## Consent (first run)

On first start, show a one-screen consent notice (NFR-3) that plainly states:
- what Vexilla observes (apps, domains, data volumes, timing),
- what it explicitly does **not** do (decrypt traffic, read content, send data out),
- where data is stored and for how long (default 30 days),
- how to pause monitoring and how to uninstall.

No dark patterns. The user must actively acknowledge before capture begins.

## Data handling

- **Storage:** local SQLite at `/var/lib/vexilla/vexilla.db`, readable only by the
  service user. Consider file-mode `0600`.
- **Retention:** default 30 days, configurable; automatic pruning (see `data-model.md`).
- **Export:** provide a plain export (JSON/CSV) so users control their own data.
- **Deletion:** `vexilla reset` clears the runtime DB; uninstall removes it.
- **The KB** (`kb.db`) contains no user data — it's shipped reference data.

## Legal posture

- Vexilla monitors the **user's own device with their consent** — the clean, intended
  use. This is fundamentally different from monitoring others' traffic.
- Do **not** position or build features for surveilling other people (e.g. secretly
  monitoring someone else's device). The consent screen and local-only design reinforce
  the intended single-user, self-transparency use.
- Third-party lists/data used to build the KB must be license-compatible and credited
  (`THIRD_PARTY.md`); see `knowledge-base.md`.

## Security of Vexilla itself

- The dashboard is read-only over the store and loopback-bound; no remote control surface.
- No inbound network listeners except loopback.
- Guarded optional deps (eBPF/scapy) must fail closed (disable feature) rather than
  crash or escalate.
- Keep the privileged collector small and auditable; enrichment/UI stay unprivileged.

## If cloud is ever added (post-MVP, explicit opt-in only)

- Must be **off by default** and clearly explained.
- Never send raw connection logs or full domain history (that *is* the user's browsing
  history). Only aggregated, non-identifying data, with consent, and documented here
  first.
- Adding any egress requires updating this document and an ADR.

## Boundary summary

| We see | We do NOT see |
|---|---|
| Which app connected | The content of any connection |
| Remote IP / domain (via DNS) | Decrypted HTTPS payloads |
| Bytes sent/received, timing | Passwords, messages, page contents |
| Active vs background | Anything after TLS is established |
