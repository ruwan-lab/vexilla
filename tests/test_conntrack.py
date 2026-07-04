"""Tests for conntrack.py — conntrack entry parsing.

Tests use crafted text lines rather than reading /proc/net/nf_conntrack
for deterministic results.
"""

from __future__ import annotations

from vexilla.collector.conntrack import _manual_parse


class TestManualParse:
    def test_simple_tcp_entry(self):
        """Parse a basic conntrack entry for an established TCP connection."""
        line = (
            "src=10.0.0.1 dst=93.184.216.34 sport=54321 dport=80 "
            "packets=5 bytes=437 src=93.184.216.34 dst=10.0.0.1 "
            "sport=80 dport=54321 packets=3 bytes=1200"
        )
        entry = _manual_parse(line)
        assert entry is not None
        assert entry.src_ip == "10.0.0.1"
        assert entry.dst_ip == "93.184.216.34"
        assert entry.src_port == 54321
        assert entry.dst_port == 80
        assert entry.bytes_sent == 437
        assert entry.bytes_recv == 1200
        assert entry.packets_sent == 5
        assert entry.packets_recv == 3

    def test_unreplied_entry(self):
        """An entry without reply direction data."""
        line = (
            "src=10.0.0.1 dst=93.184.216.34 sport=54321 dport=443 "
            "[UNREPLIED]"
        )
        entry = _manual_parse(line)
        assert entry is not None
        assert entry.src_ip == "10.0.0.1"
        assert entry.dst_ip == "93.184.216.34"
        assert entry.bytes_sent == 0
        assert entry.bytes_recv == 0

    def test_entry_without_packets(self):
        """An entry without byte/packet counters still produces a result."""
        line = "src=10.0.0.1 dst=1.2.3.4 sport=12345 dport=53"
        entry = _manual_parse(line)
        assert entry is not None
        assert entry.bytes_sent == 0
        assert entry.bytes_recv == 0

    def test_missing_fields(self):
        """Entry missing critical fields returns None."""
        line = "src=10.0.0.1 sport=12345"
        entry = _manual_parse(line)
        assert entry is None

    def test_large_bytes(self):
        """Large byte counts are handled correctly."""
        line = (
            "src=10.0.0.1 dst=1.2.3.4 sport=40000 dport=443 "
            "packets=15000 bytes=104857600 src=1.2.3.4 dst=10.0.0.1 "
            "sport=443 dport=40000 packets=12000 bytes=52428800"
        )
        entry = _manual_parse(line)
        assert entry is not None
        assert entry.bytes_sent == 104857600  # 100 MB
        assert entry.bytes_recv == 52428800  # 50 MB
        assert entry.packets_sent == 15000
        assert entry.packets_recv == 12000
