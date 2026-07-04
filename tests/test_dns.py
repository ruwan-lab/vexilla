"""Tests for dns.py — DNS response packet parsing.

Uses crafted raw DNS response bytes for deterministic testing.
"""

from __future__ import annotations

import struct
from typing import Optional

from vexilla.collector.dns import DnsCapturer


def _make_dns_response(domain: str, ip: str, rtype: int = 1) -> bytes:
    """Build a minimal valid DNS response packet for testing.

    rtype: 1=A, 28=AAAA
    """
    # DNS header (12 bytes): id=0x1234, flags=0x8180 (response, no error),
    # qdcount=1, ancount=1, nscount=0, arcount=0
    header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)

    # Question section: encoded domain name + QTYPE + QCLASS
    question = _encode_dns_name(domain) + struct.pack("!HH", rtype, 1)

    # Answer section: compressed name + TYPE + CLASS + TTL + RDLENGTH + RDATA
    answer_name = b"\xc0\x0c"  # pointer to name in question (offset 12)
    ttl = 300
    if rtype == 1:  # A record
        parts = [int(x) for x in ip.split(".")]
        rdata = bytes(parts)
        rdlength = 4
    elif rtype == 28:  # AAAA record
        # Simplify: not implemented for test yet
        rdlength = 0
        rdata = b""
    else:
        rdlength = 0
        rdata = b""

    answer = answer_name + struct.pack("!HHIH", rtype, 1, ttl, rdlength) + rdata

    return header + question + answer


def _encode_dns_name(name: str) -> bytes:
    """Encode a domain name in DNS label format."""
    encoded = b""
    for label in name.split("."):
        encoded += bytes([len(label)]) + label.encode("ascii")
    encoded += b"\x00"
    return encoded


class TestDnsParsing:
    def test_parse_a_record(self):
        """Parse a single A record DNS response."""
        capturer = DnsCapturer()
        # Mock the _available flag and _sock to avoid needing raw socket
        raw_response = _make_dns_response("example.com", "93.184.216.34")

        capturer._parse_dns_response(raw_response)

        result = capturer.lookup("93.184.216.34")
        assert result is not None
        assert result.domain == "example.com"
        assert result.name_source == "dns"

    def test_parse_multiple_ips(self):
        """Cache multiple IPs from multiple DNS responses."""
        capturer = DnsCapturer()

        resp1 = _make_dns_response("google.com", "142.250.80.46")
        capturer._parse_dns_response(resp1)

        resp2 = _make_dns_response("cloudflare.com", "104.16.132.229")
        capturer._parse_dns_response(resp2)

        assert capturer.lookup("142.250.80.46") is not None
        assert capturer.lookup("142.250.80.46").domain == "google.com"
        assert capturer.lookup("104.16.132.229").domain == "cloudflare.com"

    def test_missing_ip_returns_none(self):
        """Lookup for an IP not in the cache returns None."""
        capturer = DnsCapturer()
        result = capturer.lookup("1.2.3.4")
        assert result is None

    def test_dns_error_response_skipped(self):
        """A DNS response with errors (RCODE != 0) is ignored."""
        capturer = DnsCapturer()

        # Build a response with RCODE=3 (NXDOMAIN)
        header = struct.pack("!HHHHHH", 0x1234, 0x8183, 1, 0, 0, 0)
        question = _encode_dns_name("nonexistent.example") + struct.pack("!HH", 1, 1)
        bad_response = header + question

        capturer._parse_dns_response(bad_response)
        assert capturer.lookup("1.2.3.4") is None

    def test_empty_response_skipped(self):
        """A DNS response with no answers is ignored."""
        capturer = DnsCapturer()

        # qdcount=1, ancount=0
        header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 0, 0, 0)
        question = _encode_dns_name("example.com") + struct.pack("!HH", 1, 1)
        empty_response = header + question

        capturer._parse_dns_response(empty_response)
        assert capturer.lookup("93.184.216.34") is None
