"""Store writer — upserts flows into the SQLite database.

Maintains an in-memory open-flow table across poll cycles
and computes byte deltas from conntrack.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

from vexilla.collector.classify import classify
from vexilla.collector.conntrack import ConntrackEntry, read_conntrack
from vexilla.collector.dns import DnsCapturer
from vexilla.collector.models import (
    ConnKey,
    FlowState,
    ProcConn,
    EndpointInfo,
    ProcInfo,
)
from vexilla.collector.procnet import read_connections
from vexilla.collector.process import ProcessResolver
from vexilla.store import Database

logger = logging.getLogger(__name__)


# Grace period in seconds before a flow that disappeared from /proc/net
# is considered closed and flushed.
FLOW_GRACE_PERIOD = 30


class FlowWriter:
    """Reads connections from /proc/net, matches to processes, attributes
    bytes from conntrack, and upserts into the store.

    Reuses the same Database instance as the rest of the app.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._process_resolver = ProcessResolver()
        self._dns_capturer = DnsCapturer()

        # In-memory open flow table: ConnKey -> FlowState
        self._open_flows: Dict[str, FlowState] = {}

        # Track last-seen for grace-period close detection
        self._now: int = 0

    def poll(self) -> None:
        """Run one poll cycle: read connections, resolve processes,
        attribute bytes, upsert to DB, close stale flows."""
        self._now = int(time.time())

        # Phase 1: Read all current connections from /proc/net
        conns = read_connections()

        # Diagnostic: log poll stats every 30 cycles (to be removed)
        _pc = getattr(self, "_diag_count", 0) + 1
        self._diag_count = _pc
        logger.info("Poll: %d external connections (%d established)", len(conns), sum(1 for c in conns if c.protocol == "tcp" and c.state == "01"))

        # Phase 2: Read conntrack for byte counters
        conntrack_entries = read_conntrack()
        ct_map = self._build_ct_map(conntrack_entries)
        logger.info("Poll: %d conntrack entries", len(conntrack_entries))

        # Phase 3: DNS capture pass
        self._dns_capturer.capture_once()

        # Phase 4: For each connection, resolve process and upsert flow
        current_keys: set[str] = set()

        # Group conns by app to minimize DB lookups
        for conn in conns:
            # Only established TCP or any UDP with external IP
            if conn.protocol == "tcp" and not conn.is_established():
                continue

            # Resolve process via ss -tnp (IP+port match) then inode fallback
            proc_info = self._process_resolver.resolve(
                conn.inode, conn.remote_ip, conn.remote_port
            )
            if proc_info is None:
                continue

            # Build conn key
            app_name = proc_info.comm
            conn_key = ConnKey(
                app_name=app_name,
                remote_ip=conn.remote_ip,
                remote_port=conn.remote_port,
                protocol=conn.protocol,
            )
            key_str = self._key_to_str(conn_key)
            current_keys.add(key_str)

            # Get byte counters from conntrack (matched by 5-tuple)
            ct_bytes_sent, ct_bytes_recv = self._match_conntrack(
                conn, proc_info, ct_map
            )

            # Classify active/background
            is_bg, evidence = classify(
                proc_info.comm, proc_info.exe_path, conn.uid,
                pid=proc_info.pid,
            )

            # Get or create App and Endpoint DB records
            app_id = self._get_or_create_app(proc_info)
            endpoint_id = self._get_or_create_endpoint(conn)

            # Upsert or create flow
            if key_str in self._open_flows:
                flow = self._open_flows[key_str]
                delta_sent = max(0, ct_bytes_sent - flow.prev_bytes_sent)
                delta_recv = max(0, ct_bytes_recv - flow.prev_bytes_recv)
                if delta_sent > 0 or delta_recv > 0:
                    self._db.execute(
                        """UPDATE flow
                           SET bytes_sent = bytes_sent + ?,
                               bytes_recv = bytes_recv + ?,
                               last_seen = ?
                           WHERE id = ?""",
                        (delta_sent, delta_recv, self._now, flow.app_id),
                    )
                    # Also update agg_hourly with deltas
                    self._upsert_agg_hourly(
                        endpoint_id, app_id, delta_sent, delta_recv,
                        is_bg, 1, self._now,
                    )
                flow.last_seen = self._now
                flow.prev_bytes_sent = ct_bytes_sent
                flow.prev_bytes_recv = ct_bytes_recv
            else:
                # New flow — insert
                cursor = self._db.execute(
                    """INSERT INTO flow
                       (app_id, endpoint_id, protocol, remote_port,
                        bytes_sent, bytes_recv, is_background,
                        started_at, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        app_id,
                        endpoint_id,
                        conn.protocol,
                        conn.remote_port,
                        ct_bytes_sent,
                        ct_bytes_recv,
                        is_bg,
                        self._now,
                        self._now,
                    ),
                )
                self._db._get_conn().commit()

                flow_id = cursor.lastrowid
                logger.info("NEW FLOW: app=%s ep=%s:%d proto=%s", app_name, conn.remote_ip, conn.remote_port, conn.protocol)
                self._open_flows[key_str] = FlowState(
                    app_id=flow_id,
                    endpoint_id=endpoint_id,
                    conn_key=conn_key,
                    is_background=is_bg,
                    started_at=self._now,
                    last_seen=self._now,
                    bytes_sent=ct_bytes_sent,
                    bytes_recv=ct_bytes_recv,
                    prev_bytes_sent=ct_bytes_sent,
                    prev_bytes_recv=ct_bytes_recv,
                )

                # Initial agg_hourly entry
                self._upsert_agg_hourly(
                    endpoint_id, app_id, ct_bytes_sent, ct_bytes_recv,
                    is_bg, 1, self._now,
                )

        # Phase 5: Close stale flows (gone from /proc/net)
        self._close_stale_flows(current_keys)

        # Phase 6: Commit all pending writes
        try:
            self._db._get_conn().commit()
        except Exception:
            pass

        # Phase 7: Log completion
        logger.info("Poll complete: %d connections, %d open flows", len(conns), len(self._open_flows))

        # Phase 7: Refresh process resolver periodically (handled internally)

    # ── Internal helpers ───────────────────────────────────────────

    def _get_or_create_app(self, proc: ProcInfo) -> int:
        """Upsert an app record; return its id.

        Manual SELECT-then-UPDATE/INSERT pattern works with
        any table constraint (UNIQUE(name) or UNIQUE(name, exe_path)).
        """
        row = self._db.execute(
            "SELECT id FROM app WHERE name = ?",
            (proc.comm,),
        ).fetchone()
        if row is not None:
            self._db.execute(
                "UPDATE app SET exe_path = COALESCE(?, exe_path), last_seen = ? WHERE id = ?",
                (proc.exe_path, self._now, row[0]),
            )
            return row[0]

        self._db.execute(
            "INSERT INTO app (name, exe_path, first_seen, last_seen) VALUES (?, ?, ?, ?)",
            (proc.comm, proc.exe_path, self._now, self._now),
        )
        row = self._db.execute(
            "SELECT id FROM app WHERE name = ?",
            (proc.comm,),
        ).fetchone()
        return row[0] if row else 0

    def _get_or_create_endpoint(self, conn: ProcConn) -> int:
        """Upsert an endpoint record; return its id."""
        # Try DNS cache first
        domain: Optional[str] = None
        name_source: str = "none"

        ep = self._dns_capturer.lookup(conn.remote_ip)
        if ep is not None and ep.domain is not None:
            domain = ep.domain
            name_source = "dns"

        row = self._db.execute(
            "SELECT id FROM endpoint WHERE ip = ?",
            (conn.remote_ip,),
        ).fetchone()
        if row is not None:
            self._db.execute(
                """UPDATE endpoint SET
                   domain = COALESCE(?, domain),
                   name_source = CASE WHEN ? IS NOT NULL THEN ? ELSE name_source END,
                   last_seen = ?
                   WHERE id = ?""",
                (domain, domain, name_source, self._now, row[0]),
            )
            return row[0]

        self._db.execute(
            "INSERT INTO endpoint (ip, domain, name_source, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
            (conn.remote_ip, domain, name_source, self._now, self._now),
        )
        row = self._db.execute(
            "SELECT id FROM endpoint WHERE ip = ?",
            (conn.remote_ip,),
        ).fetchone()
        return row[0] if row else 0

    def _upsert_agg_hourly(
        self,
        endpoint_id: int,
        app_id: int,
        bytes_sent: int,
        bytes_recv: int,
        is_background: int,
        conn_count: int,
        timestamp: int,
    ) -> None:
        """Upsert an agg_hourly row for the given hour."""
        hour_start = (timestamp // 3600) * 3600
        bg_bytes = bytes_sent + bytes_recv if is_background else 0

        self._db.execute(
            """INSERT INTO agg_hourly
               (hour_start, app_id, endpoint_id, bytes_sent, bytes_recv, conn_count, bg_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(hour_start, app_id, endpoint_id) DO UPDATE SET
                   bytes_sent = bytes_sent + ?,
                   bytes_recv = bytes_recv + ?,
                   conn_count = conn_count + ?,
                   bg_bytes = bg_bytes + ?""",
            (
                hour_start, app_id, endpoint_id,
                bytes_sent, bytes_recv, conn_count, bg_bytes,
                bytes_sent, bytes_recv, conn_count, bg_bytes,
            ),
        )

    def _close_stale_flows(self, current_keys: set[str]) -> None:
        """Remove flows that disappeared from /proc/net beyond grace period."""
        stale_keys = []
        for key_str, flow in self._open_flows.items():
            if key_str not in current_keys:
                if self._now - flow.last_seen > FLOW_GRACE_PERIOD:
                    stale_keys.append(key_str)

        for key in stale_keys:
            del self._open_flows[key]
            logger.debug("Closed stale flow: %s", key)

    @staticmethod
    def _build_ct_map(
        entries: list[ConntrackEntry],
    ) -> Dict[Tuple[str, int, str, int], Tuple[int, int]]:
        """Build 5-tuple -> (bytes_sent, bytes_recv) lookup from conntrack.

        Key: (src_ip, src_port, dst_ip, dst_port)
        Note: the 'src' in conntrack is the local machine for outbound conns.
        """
        ct_map: Dict[Tuple[str, int, str, int], Tuple[int, int]] = {}
        for entry in entries:
            key = (entry.src_ip, entry.src_port, entry.dst_ip, entry.dst_port)
            ct_map[key] = (entry.bytes_sent, entry.bytes_recv)
        return ct_map

    @staticmethod
    def _match_conntrack(
        conn: ProcConn,
        proc: ProcInfo,
        ct_map: Dict[Tuple[str, int, str, int], Tuple[int, int]],
    ) -> Tuple[int, int]:
        """Match a /proc/net connection to conntrack by 5-tuple.

        Returns (bytes_sent, bytes_recv). Falls back to (0,0) if no match.
        """
        key = (conn.local_ip, conn.local_port, conn.remote_ip, conn.remote_port)
        result = ct_map.get(key)
        if result is not None:
            return result

        # Try reverse direction (conntrack may have swapped src/dst for UDP)
        rev_key = (conn.remote_ip, conn.remote_port, conn.local_ip, conn.local_port)
        result = ct_map.get(rev_key)
        if result is not None:
            return result

        return (0, 0)

    @staticmethod
    def _key_to_str(key: ConnKey) -> str:
        return f"{key.app_name}@{key.remote_ip}:{key.remote_port}/{key.protocol}"
