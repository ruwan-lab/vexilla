"""Conntrack reader — byte/packet counters from /proc/net/nf_conntrack.

Falls back to `ss -tni` when conntrack is unavailable.
Also attempts to load the nf_conntrack kernel module at startup.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from vexilla.collector.models import ConntrackEntry

logger = logging.getLogger(__name__)

CONNTRACK_PATH = Path("/proc/net/nf_conntrack")

# Each TCP connection from `ss -tni` spans two lines:
#   ESTAB 0 0  local_ip:port  remote_ip:port
#        cubic wscale:... bytes_sent:1234 bytes_acked:1234 bytes_received:5678 ...
_SS_LINE1 = re.compile(
    r"ESTAB\s+\d+\s+\d+\s+"
    r"(?P<local>[^\s]+):(?P<lport>\d+)\s+"
    r"(?P<remote>[^\s]+):(?P<rport>\d+)"
)
_SS_BYTES = re.compile(
    r"bytes_sent:(?P<sent>\d+)\s+"
    r"bytes_acked:(?P<acked>\d+)\s+"
    r"bytes_received:(?P<recv>\d+)"
)


def _ensure_conntrack_module() -> None:
    """Try to load the nf_conntrack kernel module (best-effort)."""
    if not CONNTRACK_PATH.exists():
        try:
            subprocess.run(
                ["modprobe", "nf_conntrack"],
                capture_output=True, timeout=2.0,
            )
        except Exception:
            pass


def read_conntrack() -> List[ConntrackEntry]:
    """Read and parse /proc/net/nf_conntrack.

    Falls back to `ss -tni` if conntrack is unavailable.
    Returns a list of ConntrackEntry objects.
    Returns empty list if neither source is available.
    """
    # Try conntrack first
    if CONNTRACK_PATH.exists():
        results = _read_conntrack_proc()
        if results:
            return results

    # Fall back to ss
    results = _read_ss_stats()
    if results:
        return results

    # Try loading the module (once) and re-check
    _ensure_conntrack_module()
    if CONNTRACK_PATH.exists():
        results = _read_conntrack_proc()
        if results:
            return results

    return []


def _read_conntrack_proc() -> List[ConntrackEntry]:
    """Parse /proc/net/nf_conntrack."""
    try:
        text = CONNTRACK_PATH.read_text()
    except (FileNotFoundError, PermissionError, OSError):
        return []

    results: List[ConntrackEntry] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        entry = _parse_conntrack_line(line)
        if entry is not None:
            results.append(entry)
    return results


def _read_ss_stats() -> List[ConntrackEntry]:
    """Parse `ss -tni` output for per-socket byte counters.

    Returns ConntrackEntry compatible list with cumulative
    bytes_sent and bytes_recv per connection.
    """
    try:
        result = subprocess.run(
            ["ss", "-tni"],
            capture_output=True, text=True, timeout=3.0,
        )
        if result.returncode != 0:
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    results: List[ConntrackEntry] = []
    lines = result.stdout.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m1 = _SS_LINE1.match(line)
        if m1:
            local_ip = m1.group("local")
            local_port = int(m1.group("lport"))
            remote_ip = m1.group("remote")
            remote_port = int(m1.group("rport"))

            # Next line should be the details
            if i + 1 < len(lines):
                detail = lines[i + 1]
                m2 = _SS_BYTES.search(detail)
                if m2:
                    bytes_sent = int(m2.group("sent"))
                    bytes_recv = int(m2.group("recv"))
                    results.append(ConntrackEntry(
                        protocol="tcp",
                        src_ip=local_ip,
                        src_port=local_port,
                        dst_ip=remote_ip,
                        dst_port=remote_port,
                        bytes_sent=bytes_sent,
                        bytes_recv=bytes_recv,
                        packets_sent=0,
                        packets_recv=0,
                    ))
            i += 1
        i += 1

    logger.debug("ss -tni: %d connections with byte counters", len(results))
    return results


def _parse_conntrack_line(line: str) -> Optional[ConntrackEntry]:
    """Parse a single conntrack entry line."""
    # Regex patterns for conntrack entry components
    _RE_PROTO = re.compile(
        r"(?P<l3>ipv4|ipv6)\s+(?P<l3num>\d+)\s+"
        r"(?P<proto>tcp|udp)\s+(?P<protonum>\d+)\s+"
    )
    _RE_TCP_STATE = re.compile(r"\d+\s+(?P<state>\w+)\s+")

    try:
        m = _RE_PROTO.match(line)
        if not m:
            return None
        proto = m.group("proto")
        rest = line[m.end():]

        if proto == "tcp":
            m2 = _RE_TCP_STATE.match(rest)
            if m2:
                rest = rest[m2.end():]

        return _manual_parse(rest)
    except (ValueError, IndexError):
        return None


def _manual_parse(attrs_text: str) -> Optional[ConntrackEntry]:
    """Parse the attribute section of a conntrack line."""
    tokens = attrs_text.split()
    src_ip = dst_ip = None
    src_port = dst_port = None
    sent_packets = sent_bytes = None
    recv_packets = recv_bytes = None
    state = "original"

    for token in tokens:
        if token == "[UNREPLIED]":
            break
        if "=" not in token:
            continue

        key, val = token.split("=", 1)

        if key == "src" and src_ip is not None and state == "original":
            state = "reply"

        if state == "original":
            if key == "src":
                src_ip = val
            elif key == "dst":
                dst_ip = val
            elif key == "sport":
                src_port = int(val)
            elif key == "dport":
                dst_port = int(val)
            elif key == "packets":
                sent_packets = int(val)
            elif key == "bytes":
                sent_bytes = int(val)
        elif state == "reply":
            if key == "packets":
                recv_packets = int(val)
            elif key == "bytes":
                recv_bytes = int(val)

    if not all([src_ip, dst_ip, src_port is not None, dst_port is not None]):
        return None

    return ConntrackEntry(
        protocol="tcp",
        src_ip=src_ip,
        src_port=src_port,
        dst_ip=dst_ip,
        dst_port=dst_port,
        bytes_sent=sent_bytes or 0,
        bytes_recv=recv_bytes or 0,
        packets_sent=sent_packets or 0,
        packets_recv=recv_packets or 0,
    )
