"""Data models for the collector — connections, flows, processes.

All plain dataclasses with no import from other collector modules.
"""

from __future__ import annotations

import dataclasses
from typing import Optional


@dataclasses.dataclass(frozen=True)
class ConnKey:
    """Unique key for a flow in the in-memory open-flow table.

    Matches (app, endpoint, protocol, remote_port) semantics from data-model.md.
    """

    app_name: str
    remote_ip: str
    remote_port: int
    protocol: str  # 'tcp' | 'udp'


@dataclasses.dataclass
class ProcInfo:
    """Resolved process information from /proc/<pid>."""

    pid: int
    comm: str  # from /proc/<pid>/comm
    exe_path: Optional[str]  # from /proc/<pid>/exe, None if inaccessible


@dataclasses.dataclass
class EndpointInfo:
    """Remote endpoint with best-known name."""

    ip: str
    port: int
    protocol: str  # 'tcp' | 'udp'
    domain: Optional[str] = None
    name_source: str = "none"  # 'dns' | 'reverse' | 'none'


@dataclasses.dataclass
class ProcConn:
    """A single connection parsed from /proc/net/{tcp,udp}{,6}."""

    protocol: str  # 'tcp' | 'udp'
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    state: str  # TCP state e.g. '0A' for established, '01' for listen
    tx_queue: int
    rx_queue: int
    inode: int  # socket inode for PID resolution
    uid: int

    def is_established(self) -> bool:
        """Return True if this is a TCP connection in ESTABLISHED state.

        TCP state hex values in /proc/net/tcp:
            01 = ESTABLISHED, 0A = LISTEN
        """
        return self.protocol == "tcp" and self.state == "01"


@dataclasses.dataclass
class ConntrackEntry:
    """A single conntrack entry for byte accounting."""

    protocol: str  # 'tcp' | 'udp'
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    bytes_sent: int  # bytes from src→dst
    bytes_recv: int  # bytes from dst→src (reverse direction)
    packets_sent: int
    packets_recv: int


@dataclasses.dataclass
class FlowState:
    """In-memory state for an open flow being tracked across poll cycles."""

    app_id: Optional[int]  # DB row id, set on first upsert
    endpoint_id: Optional[int]
    conn_key: ConnKey
    is_background: int  # 0=active, 1=background
    started_at: int  # epoch seconds of first sighting
    last_seen: int  # epoch seconds
    bytes_sent: int  # cumulative from conntrack
    bytes_recv: int
    prev_bytes_sent: int  # last poll's value for delta
    prev_bytes_recv: int
