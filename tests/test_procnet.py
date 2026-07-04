"""Tests for procnet.py — /proc/net parsing.

We test with crafted hex strings rather than real /proc/net files
so the tests are deterministic and don't depend on system state.
"""

from __future__ import annotations

from pathlib import Path

from vexilla.collector.procnet import (
    _hex_ip_port,
    _is_external,
    read_connections,
)


class TestHexIpPort:
    def test_ipv4_localhost(self):
        """0100007F:0035 -> 127.0.0.1:53"""
        ip, port = _hex_ip_port("0100007F:0035")
        assert ip == "127.0.0.1"
        assert port == 53

    def test_ipv4_google(self):
        """Parses a public IP correctly (reverse hex)."""
        # 8.8.8.8 -> 08080808 in little-endian hex
        ip, port = _hex_ip_port("08080808:01BB")
        assert ip == "8.8.8.8"
        assert port == 443

    def test_ipv4_cloudflare(self):
        """0101A8C0 -> 192.168.1.1."""
        # /proc/net stores ntohl'd values. For 192.168.1.1 (0xC0A80101),
        # ntohl on LE gives 0x0101A8C0.
        ip, port = _hex_ip_port("0101A8C0:0050")
        assert ip == "192.168.1.1"
        assert port == 80

    def test_ipv6_mapped_ipv4(self):
        """IPv4-mapped IPv6 address (::ffff:192.168.1.1)."""
        # Each 32-bit word is ntohl'd in /proc/net6:
        # word3 (0xC0A80101) → ntohl → 0x0101A8C0
        raw = "0000000000000000FFFF00000101A8C0:01BB"
        ip, port = _hex_ip_port(raw)
        assert ip == "192.168.1.1"
        assert port == 443

    def test_ipv6(self):
        """Raw IPv6 address (::1)."""
        # ::1 = 0x00000000000000000000000000000001 in BE
        # word3 ntohl(0x00000001) on LE = 0x01000000
        raw = "00000000000000000000000001000000:01BB"
        ip, port = _hex_ip_port(raw)
        assert ip == "::1"
        assert port == 443


class TestIsExternal:
    def test_loopback_is_not_external(self):
        assert not _is_external("127.0.0.1")
        assert not _is_external("127.0.0.2")
        assert not _is_external("::1")

    def test_private_is_not_external(self):
        assert not _is_external("10.0.0.1")
        assert not _is_external("10.0.0.0")
        assert not _is_external("172.16.0.1")
        assert not _is_external("192.168.1.1")

    def test_link_local_is_not_external(self):
        assert not _is_external("169.254.1.1")
        assert not _is_external("fe80::1")

    def test_multicast_is_not_external(self):
        assert not _is_external("224.0.0.1")
        assert not _is_external("ff02::1")

    def test_public_ip_is_external(self):
        assert _is_external("8.8.8.8")
        assert _is_external("93.184.216.34")
        assert _is_external("1.1.1.1")
        assert _is_external("2001:4860:4860::8888")

    def test_unspecified_is_not_external(self):
        assert not _is_external("0.0.0.0")
        assert not _is_external("::")


class TestReadConnections:
    """Light integration test: read_connections() should not crash
    and should return a list (possibly empty if running in a container
    with no external connections)."""

    def test_returns_list(self):
        conns = read_connections()
        assert isinstance(conns, list)
        # All returned items should be valid ProcConn objects
        for conn in conns:
            assert conn.remote_ip is not None
            assert conn.remote_port > 0
            assert conn.protocol in ("tcp", "udp")
