# Tech stack & rationale

Guiding rule: **minimal dependencies, stdlib where possible, Python-first** (matches
the founder's strengths and keeps install simple).

| Concern | Choice | Rationale | Alternatives rejected |
|---|---|---|---|
| Language | **Python 3.11+** | Founder fluent; rich system libs; fast enough for observe-only. | Go/Rust: faster but slower to build the insight layer, the actual value. |
| Connection capture (MVP) | **`/proc/net` + `/proc/<pid>/fd` + conntrack** | No compilation, works on any kernel, no special toolchain. | Pure eBPF-first: better data but higher install friction. |
| Connection capture (enhanced) | **eBPF via `bcc` / `bpftrace`** | Accurate per-PID byte accounting, low overhead. | Kept optional to protect NFR-12 (graceful degradation). |
| DNS mapping | **AF_PACKET raw socket, manual DNS parse** (or `scapy` optional) | Passive, no resolver reconfiguration, no MITM. | Local DNS proxy: more setup, breaks "zero config". |
| Store | **SQLite (stdlib `sqlite3`, WAL)** | Zero-install, single file, crash-safe, great for local analytics. | Postgres/embedded server: overkill, violates simplicity. |
| Knowledge base | **Bundled read-only SQLite `kb.db`** | Ships as data, fully offline, instant lookups. | Runtime API: violates privacy-first + offline. |
| API / Web | **FastAPI + Jinja2 + HTMX** | Server-rendered, tiny JS, fast to build, no SPA toolchain. | React SPA: heavier, unnecessary for local read-only views. |
| Charts | **Lightweight (inline SVG / small lib)** | Keep the frontend dependency-free. | Heavy dashboards: against footprint goals. |
| CLI | **Typer** | Ergonomic, minimal, matches FastAPI author's style. | argparse: fine but more boilerplate. |
| Packaging | **`pipx` install + `install.sh` + systemd unit** | 1–2 step install (NFR-6). | Docker: adds a runtime, poor fit for a host network agent. |
| LLM (build-time only) | **Any capable model, offline batch** | Builds the KB once; never at user runtime. | Runtime cloud LLM: privacy landmine (ADR-0003). |
| License | **MIT** | Permissive; we reuse only techniques + public lists, not GPL code. | GPL-3: only needed if embedding OpenSnitch code (ADR-0004/0005). |

## Dependency budget (MVP)

Keep the required set small: `fastapi`, `uvicorn`, `jinja2`, `typer`, `pydantic`.
Optional extras (guarded imports): `bcc`/`bpftrace`, `scapy`. Everything else stdlib.

## Privileges

Only the collector needs elevated capabilities: `CAP_NET_RAW` (packet capture),
`CAP_NET_ADMIN` (conntrack byte counters), and `CAP_SYS_PTRACE` +
`CAP_DAC_READ_SEARCH` (read other users' `/proc/<pid>/fd` and `/proc/<pid>/exe`
to attribute connections to apps). Grant all four via systemd
`AmbientCapabilities=` **and** list them in `CapabilityBoundingSet=` — the bounding
set is a ceiling that applies even to root, so any capability omitted there is
unavailable regardless of uid.

## Runtime layout

```
/usr/lib/vexilla/            app code (or pipx venv)
/var/lib/vexilla/vexilla.db  runtime database
/usr/share/vexilla/kb.db     shipped knowledge base (read-only)
/etc/vexilla/config.toml     optional overrides (all have defaults)
127.0.0.1:8787               dashboard
```
