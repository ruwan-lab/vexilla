"""Parse /proc/net/{tcp,tcp6,udp,udp6} for active connections.

Each file contains a header row followed by lines in this format:

    sl  local_address  rem_address  st  tx_queue:rx_queue  tr  tm->when  retrnsmt
    uid  timeout  inode

We extract: local/remote address:port, state, inode, uid, queues.
Outbound (non-loopback, non-private) connections are returned.
"""

from __future__ import annotations

import ipaddress
import logging
import struct
from pathlib import Path
from typing import List

from vexilla.collector.models import ProcConn

logger = logging.getLogger(__name__)

PROC_NET = Path("/proc/net")

# TCP states (hex values from /proc/net/tcp)
# 01 = TCP_ESTABLISHED, 0A = TCP_LISTEN
ESTABLISHED_HEX = "01"
LISTEN_HEX = "0A"

# IP ranges considered private / non-external
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _hex_ip_port(hex_str: str) -> tuple[str, int]:
    """Parse a hex-encoded ip:port from /proc/net format.

    The kernel stores IP addresses in /proc/net as hex strings of the
    ntohl'd value. On little-endian this means the hex string bytes
    are in LE 32-bit word order. We read each 32-bit word as
    little-endian — which directly gives us the network-byte-order
    IP value (the kernel already applied ntohl before printing).

    TCP: '0100007F:0035' -> ('127.0.0.1', 53)
    TCP6: '0000000000000000FFFF00000101A8C0:01BB' -> ('192.168.1.1', 443)
    """
    addr_hex, port_hex = hex_str.split(":")
    port = int(port_hex, 16)
    raw = bytes.fromhex(addr_hex)

    if len(raw) == 4:
        # IPv4: hex is ntohl'd LE → read as LE 32-bit gives the
        # correct network-byte-order IP value directly
        ip_int = struct.unpack("<I", raw)[0]
        ip = ipaddress.IPv4Address(ip_int)
    elif len(raw) == 16:
        # IPv6: 4 × 32-bit words, each stored in LE (ntohl'd)
        words = []
        for i in range(0, 16, 4):
            word = struct.unpack("<I", raw[i : i + 4])[0]
            words.append(struct.pack(">I", word))
        ip_bytes = b"".join(words)
        ip = ipaddress.IPv6Address(ip_bytes)
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped), port
    else:
        ip = ipaddress.IPv4Address(raw)

    return str(ip), port


def _is_external(ip_str: str) -> bool:
    """Return True if the IP is a routable (non-private, non-loopback) address."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    if addr.is_loopback or addr.is_link_local or addr.is_multicast:
        return False
    if addr.is_private:
        return False
    if addr.is_unspecified:
        return False
    return True


def _parse_proc_net_file(
    path: Path, protocol: str
) -> List[ProcConn]:
    """Parse a single /proc/net/{tcp,udp}{,6} file."""
    results: List[ProcConn] = []
    try:
        text = path.read_text()
    except FileNotFoundError:
        logger.debug("File not found: %s", path)
        return results
    except PermissionError:
        logger.warning("Permission denied reading %s", path)
        return results

    lines = text.strip().split("\n")
    if not lines:
        return results

    # Skip header line
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 12:
            continue

        try:
            local_hex = parts[1]
            rem_hex = parts[2]
            state_hex = parts[3]
            tx_rx = parts[4]
            uid_str = parts[7]
            inode_str = parts[9]

            local_ip, local_port = _hex_ip_port(local_hex)
            remote_ip, remote_port = _hex_ip_port(rem_hex)

            # Parse tx_queue:rx_queue
            tx_str, rx_str = tx_rx.split(":")
            tx_queue = int(tx_str, 16)
            rx_queue = int(rx_str, 16)

            uid = int(uid_str)
            inode = int(inode_str)

            # Filter: only external outbound connections
            if not _is_external(remote_ip):
                continue

            results.append(
                ProcConn(
                    protocol=protocol,
                    local_ip=local_ip,
                    local_port=local_port,
                    remote_ip=remote_ip,
                    remote_port=remote_port,
                    state=state_hex,
                    tx_queue=tx_queue,
                    rx_queue=rx_queue,
                    inode=inode,
                    uid=uid,
                )
            )
        except (IndexError, ValueError, OSError) as exc:
            logger.debug("Skipping malformed line in %s: %s — %s", path.name, line, exc)
            continue

    return results


def read_connections() -> List[ProcConn]:
    """Read all external outbound connections from /proc/net.

    Returns a list of ProcConn entries (TCP and UDP, v4 and v6)
    that connect to non-private, non-loopback external IPs.
    """
    conns: List[ProcConn] = []

    for fname, proto in [
        ("tcp", "tcp"),
        ("tcp6", "tcp"),
        ("udp", "udp"),
        ("udp6", "udp"),
    ]:
        path = PROC_NET / fname
        conns.extend(_parse_proc_net_file(path, proto))

    return conns
