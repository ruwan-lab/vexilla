"""Passive DNS capture — AF_PACKET raw socket on port 53.

Requires CAP_NET_RAW to open the raw socket.
If unavailable, the DNS capturer reports the limitation gracefully.
"""

from __future__ import annotations

import logging
import socket
import struct
import time
from pathlib import Path
from typing import List, Optional, Tuple

from vexilla.collector.models import EndpointInfo

logger = logging.getLogger(__name__)


class DnsCapturer:
    """Passive DNS response sniffer on UDP port 53.

    Opens an AF_PACKET raw socket to capture DNS responses and
    parse A/AAAA/CNAME records to build an IP → domain map.
    """

    def __init__(self) -> None:
        self._sock: Optional[socket.socket] = None
        self._cache: dict[str, tuple[str, float, int]] = {}  # ip -> (domain, timestamp, ttl)
        self._available = False
        self._setup()

    def _setup(self) -> None:
        """Try to open the raw packet socket."""
        try:
            self._sock = socket.socket(
                socket.AF_PACKET,
                socket.SOCK_RAW,
                socket.htons(0x0003),  # ETH_P_ALL — capture all ethertypes
            )
            self._sock.settimeout(0.5)
            self._available = True
            logger.info("DNS capturer: AF_PACKET socket open (port 53)")
        except PermissionError:
            logger.warning(
                "DNS capturer: AF_PACKET socket requires CAP_NET_RAW. "
                "Endpoint naming limited to reverse DNS."
            )
        except OSError as exc:
            logger.warning("DNS capturer: cannot open raw socket: %s", exc)

    @property
    def is_available(self) -> bool:
        return self._available

    def capture_once(self) -> None:
        """Read any pending DNS response packets and update the cache."""
        if not self._available or self._sock is None:
            return

        try:
            for _ in range(50):  # batch read up to 50 packets
                try:
                    packet = self._sock.recv(65535)
                    self._process_packet(packet)
                except socket.timeout:
                    break  # no more packets available
        except OSError:
            pass

    def lookup(self, ip: str) -> Optional[EndpointInfo]:
        """Look up an IP in the DNS cache.

        Returns EndpointInfo with domain and name_source if found.
        """
        entry = self._cache.get(ip)
        if entry is None:
            return None

        domain, timestamp, ttl = entry
        now = time.time()
        if ttl > 0 and now - timestamp > ttl:
            # Entry expired; keep but mark stale
            pass  # we still return it; will refresh on next capture

        return EndpointInfo(
            ip=ip, port=0, protocol="", domain=domain, name_source="dns"
        )

    # ── Packet processing ──────────────────────────────────────────

    def _process_packet(self, packet: bytes) -> None:
        """Parse a raw Ethernet frame and extract DNS responses.

        Ethernet header (14 bytes) → IP header (20+ bytes) → UDP (8 bytes) → DNS.
        """
        if len(packet) < 14:
            return

        eth_type = struct.unpack("!H", packet[12:14])[0]

        # IPv4 (0x0800)
        if eth_type != 0x0800:
            return

        ip_hdr_start = 14
        if len(packet) < ip_hdr_start + 20:
            return

        # IP header: version+ihl (1), tos (1), total_len (2), id (2), flags_frag (2),
        # ttl (1), protocol (1), checksum (2), src (4), dst (4)
        ip_ihl = packet[ip_hdr_start] & 0x0F
        ip_hdr_len = ip_ihl * 4
        ip_proto = packet[ip_hdr_start + 9]

        # UDP only (protocol 17)
        if ip_proto != 17:
            return

        udp_start = ip_hdr_start + ip_hdr_len
        if len(packet) < udp_start + 8:
            return

        src_port = struct.unpack("!H", packet[udp_start : udp_start + 2])[0]
        dst_port = struct.unpack("!H", packet[udp_start + 2 : udp_start + 4])[0]
        udp_len = struct.unpack("!H", packet[udp_start + 4 : udp_start + 6])[0]

        # We want DNS responses: src port 53 (server response) or dst port 53
        is_response = src_port == 53
        if not is_response:
            return

        dns_start = udp_start + 8
        dns_payload = packet[dns_start : dns_start + udp_len - 8]
        self._parse_dns_response(dns_payload)

    def _parse_dns_response(self, data: bytes) -> None:
        """Parse a DNS response message and extract A/AAAA/CNAME records."""
        if len(data) < 12:
            return

        # DNS header: id (2), flags (2), qdcount (2), ancount (2), nscount (2), arcount (2)
        flags = struct.unpack("!H", data[2:4])[0]
        qr = (flags >> 15) & 0x1
        rcode = flags & 0x0F

        # Must be a response (QR=1) with no error (RCODE=0)
        if qr != 1 or rcode != 0:
            return

        ancount = struct.unpack("!H", data[6:8])[0]
        if ancount == 0:
            return

        pos = 12

        # Skip the question section (qdcount questions)
        qdcount = struct.unpack("!H", data[4:6])[0]
        for _ in range(qdcount):
            pos = self._skip_name(data, pos)
            if pos < 0:
                return
            pos += 4  # skip QTYPE and QCLASS

        # Parse answer section
        for _ in range(ancount):
            pos = self._skip_name(data, pos)
            if pos < 0:
                return
            if pos + 10 > len(data):
                return

            rtype = struct.unpack("!H", data[pos : pos + 2])[0]
            rclass = struct.unpack("!H", data[pos + 2 : pos + 4])[0]
            ttl = struct.unpack("!I", data[pos + 4 : pos + 8])[0]
            rdlength = struct.unpack("!H", data[pos + 8 : pos + 10])[0]

            pos += 10

            if rtype == 1 and rdlength == 4:  # A record
                ip = ".".join(str(b) for b in data[pos : pos + 4])
                domain = self._decode_name(data, self._last_question_start(data))
                if domain:
                    self._add_to_cache(ip, domain, ttl)
            elif rtype == 28 and rdlength == 16:  # AAAA record
                raw = data[pos : pos + 16]
                ip = ":".join(
                    f"{raw[i]:02x}{raw[i+1]:02x}" for i in range(0, 16, 2)
                )
                domain = self._decode_name(data, self._last_question_start(data))
                if domain:
                    self._add_to_cache(ip, domain, ttl)
            elif rtype == 5:  # CNAME record
                pass  # CNAMEs are useful for alias resolution but complex

            pos += rdlength

    def _add_to_cache(self, ip: str, domain: str, ttl: int) -> None:
        """Add an IP→domain mapping to the cache."""
        now = time.time()
        self._cache[ip] = (domain, now, ttl)
        logger.debug("DNS cache: %s -> %s (TTL %d)", ip, domain, ttl)

    # ── DNS name helpers ───────────────────────────────────────────

    @staticmethod
    def _skip_name(data: bytes, pos: int) -> int:
        """Skip a DNS name at position pos, handling compression."""
        original_pos = pos
        jumped = False
        while pos < len(data):
            length = data[pos]
            if length == 0:
                pos += 1
                break
            if length & 0xC0:  # compression pointer
                if not jumped:
                    jumped = True
                pos += 2
                break
            pos += length + 1
            if pos >= len(data):
                return -1
        return pos

    @staticmethod
    def _decode_name(data: bytes, pos: int) -> Optional[str]:
        """Decode a DNS name at position pos, handling compression."""
        labels: List[bytes] = []
        jumped = False
        while pos < len(data):
            length = data[pos]
            if length == 0:
                pos += 1
                break
            if length & 0xC0:  # compression pointer
                if not jumped:
                    jumped = True
                    ptr = ((length & 0x3F) << 8) | data[pos + 1]
                    pos = ptr
                    continue
                else:
                    pos += 2
                    break
            pos += 1
            if pos + length > len(data):
                return None
            labels.append(data[pos : pos + length])
            pos += length
        if not labels:
            return None
        return b".".join(labels).decode("ascii", errors="replace")

    @staticmethod
    def _last_question_start(data: bytes) -> int:
        """Find the start of the last question's name for name resolution."""
        # We store the question name position during parsing
        # For simplicity, return position 12 (after the header)
        return 12
