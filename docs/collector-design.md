# Collector design

The collector is the only privileged component. It observes network activity and
writes normalized facts to the store. It makes **no judgments** and does **no
enrichment**. It never decrypts traffic (ADR-0006).

## Responsibilities

1. Enumerate active outbound connections and attribute each to a process.
2. Measure bytes sent/received per connection.
3. Build an `IP → domain` map via passive DNS capture.
4. Classify each connection as active vs background.
5. Write/update `flow`, `endpoint`, `app`, `dns_cache` rows (see `data-model.md`).

## Two capture paths

### Path A — Poll-based (MVP default, no compilation)

Runs on any kernel ≥ 5.4, no toolchain, degrades gracefully (NFR-12).

**Connections + attribution:**
- Parse `/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/udp`, `/proc/net/udp6`.
  Each row gives local/remote addr:port, state, and the socket **inode**.
- Build an `inode → PID` map by scanning `/proc/<pid>/fd/*` symlinks
  (`socket:[<inode>]`). Cache it; refresh on a slower cadence than the socket poll.
- From PID, resolve `name` (`/proc/<pid>/comm`) and `exe_path` (`/proc/<pid>/exe`).
- Poll interval: default **2 s** (configurable). Only outbound, non-loopback,
  non-private-peer connections are recorded as "external" (private ranges flagged
  separately, see below).

**Byte accounting:**
- Read conntrack (`/proc/net/nf_conntrack` or `conntrack -L`) which exposes per-flow
  `bytes=`/`packets=` counters. Match conntrack entries to `/proc/net` connections by
  the 5-tuple (proto, src, sport, dst, dport) to attribute bytes to a PID's flow.
- If conntrack is unavailable, fall back to socket-level counters where exposed, else
  record connection existence + counts without precise byte volume (mark `bytes=0`,
  `evidence.byte_source='unavailable'`). Never block on missing data.

### Path B — eBPF (enhanced accuracy, optional)

When `bcc`/`bpftrace` and a suitable kernel are present, attach to kernel tracepoints/
kprobes:
- `tcp_sendmsg` / `tcp_cleanup_rbuf` (or `sock_sendmsg`/`sock_recvmsg`) for accurate
  per-PID, per-socket byte counts without polling conntrack.
- `security_socket_connect` / `tcp_connect` for connection-open events with PID.

eBPF gives cleaner attribution and lower overhead but must be **strictly optional**:
detect availability at startup, log which path is active, and expose it in
`vexilla status`. Same output schema regardless of path.

## Passive DNS capture

- Open an **AF_PACKET** raw socket (needs `CAP_NET_RAW`) and filter UDP/TCP port 53.
- Parse DNS **responses**: extract A/AAAA answers and CNAME chains; write `(ip, domain)`
  into `dns_cache` with TTL and `observed_at`.
- When naming an endpoint, prefer the most recent `dns_cache` hit for that IP
  (`name_source='dns'`); if none, attempt a single reverse PTR lookup
  (`name_source='reverse'`); else leave `domain=NULL` (`name_source='none'`).

**Known limitations (document these to users, do not hide them):**
- **DoH/DoT** (encrypted DNS, e.g. browsers using their own resolver) bypasses port-53
  capture → those endpoints may stay unnamed or fall back to reverse DNS.
- CDNs / shared IPs can map to many domains; last-writer-wins may misattribute. Store
  all observations; UI can show "possibly one of: …".
- We read **SNI/DNS only** — never payloads. This is a deliberate privacy boundary.

## Active vs background classification

`is_background` heuristic (MVP, pragmatic — refine later):
- A flow is **active** if its owning process is the current foreground GUI app OR the
  connection began within N seconds of user input activity.
- Otherwise **background**.
- Foreground/idle detection on Linux is imperfect headless; MVP approximation:
  - Treat known interactive apps (browsers, mail, chat) as active when they have a
    visible window (via the display server if available), else background.
  - Treat system/daemon processes (no controlling TTY, in a system cgroup/service) as
    background by default.
- The exact rule lives in code as a documented function; `evidence` records which
  branch fired so it stays explainable.

## Write strategy

- Maintain an in-memory table of **open flows** keyed by (pid/app, endpoint, proto,
  remote_port). On each poll: upsert the flow row, add byte deltas, bump `last_seen`.
- Close/flush flows that disappear from `/proc/net` for > grace period.
- Batch writes in a transaction per poll cycle to keep SQLite happy under WAL.

## Failure & safety

- The collector must **never** modify, drop, or delay traffic (observe-only is structural).
- Any capture path failure degrades to a lesser path and logs it; it never crashes the
  service. Missing data is recorded as missing, not faked.
- Capabilities required (granted via the systemd unit):
  - `CAP_NET_RAW` — AF_PACKET DNS capture.
  - `CAP_NET_ADMIN` — read conntrack byte counters.
  - `CAP_SYS_PTRACE` + `CAP_DAC_READ_SEARCH` — read `/proc/<pid>/fd` and
    `/proc/<pid>/exe` of processes owned by *other* users (the desktop user's
    browsers, etc.) to map socket inodes to the owning app. These are read-only
    caps; the collector never writes or ptrace-attaches. Without them the daemon
    starts cleanly but attributes zero connections even when run as root, because
    a `CapabilityBoundingSet=` that omits them strips them from root too.

## Acceptance checks

- Given a known download in a browser, the collector attributes the bytes to that
  browser's app row and names the endpoint from DNS.
- Given a background updater (e.g. a package manager daemon) fetching data, the flow is
  marked `is_background=1`.
- With eBPF unavailable, the poll path still produces flows (possibly `bytes=0` if no
  conntrack) without error.
