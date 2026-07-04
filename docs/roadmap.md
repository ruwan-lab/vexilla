# Roadmap

Direction beyond the MVP. Each phase is optional and should only start once the prior
phase is solid. Nothing here weakens the privacy guarantees in `privacy.md`; anything
that adds network egress requires a new ADR.

## Now — MVP (see `mvp-scope.md`)
Linux, observe-only, poll-based capture, offline KB, plain-language insights, local
dashboard + CLI.

## Phase A — Accuracy & depth (post-MVP)
- **eBPF collector path** as default where available (accurate per-PID bytes, lower
  overhead). Poll path remains the fallback.
- Better active/background detection (session/idle signals).
- Larger KB (~50k domains); alias coverage for noisy subdomains.
- Weekly/monthly trends and per-app history views.

## Phase B — Reach more users
- **macOS support** via a NetworkExtension system extension (needs Apple entitlements +
  notarization; significant effort — its own ADR).
- **Windows support** via WFP/ETW.
- Packaged distro builds (.deb/.rpm/AUR) for even simpler install.

## Phase C — Optional control (careful, opt-in)
- **Blocking / per-app or per-domain allow-lists** (the Portmaster-style step). This is a
  major shift from observe-only: needs fail-safe design so users can't break their own
  network. Requires ADR superseding ADR-0002.
- One-click "reduce this tracker" actions (e.g. apply a local DNS blocklist), always
  reversible.

## Phase D — Optional cloud (strictly opt-in, off by default)
- **Cross-device / family dashboard** (aggregated, non-identifying data only).
- **Opt-in KB refresh** download so explanations improve without an app update.
- Any egress must follow `privacy.md`'s cloud rules and a new ADR first.

## Mobile (hard — separate track)
- **Android:** local-VPN (`VpnService`) capture, no root; app attribution is limited —
  scope carefully.
- **iOS:** cannot attribute traffic to individual apps; only aggregate via a local VPN.
  Likely a reduced "network transparency" experience, not feature parity.
- Treat mobile as a distinct product decision, not a simple port.

## Non-goals (unless the product's identity changes)
- Antivirus / malware removal.
- Enterprise SOC / SIEM features.
- TLS interception / payload inspection (permanent non-goal — ADR-0006).
- Selling or monetizing user data (permanent non-goal).

## Sustainability (the project is non-commercial-first)
- Keep the agent free and MIT open-source to build trust and community (Portmaster model).
- If funding is ever needed: optional paid **hosted** cross-device/family dashboard
  (Phase D) — never by degrading the local, private core.
