"""Optional eBPF collector path for accurate per-PID byte accounting.

Uses bcc Python bindings to attach kprobes for tcp_sendmsg and
tcp_cleanup_rbuf. Falls back gracefully when bcc is unavailable.

Same output schema as the poll-based path — interchangeable.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Will be set to True if bcc import succeeds
_BCC_AVAILABLE = False
_bcc = None

try:
    import bcc as _bcc  # type: ignore
    from bcc import BPF  # type: ignore

    _BCC_AVAILABLE = True
except ImportError:
    pass


@dataclass
class EbpfByteSample:
    """A single eBPF byte accounting sample."""

    pid: int
    comm: str
    daddr: str
    dport: int
    sport: int
    bytes_sent: int = 0
    bytes_recv: int = 0


# eBPF C program that tracks per-socket TCP byte counts.
# Keyed by (pid, sock_ptr) to track unique connections.
BPF_PROGRAM = """
#include <net/sock.h>
#include <linux/socket.h>
#include <net/inet_sock.h>
#include <uapi/linux/ptrace.h>

BPF_HASH(byte_map, u64, struct byte_count);

struct byte_count {
    u64 sent;
    u64 recv;
    u32 pid;
    char comm[TASK_COMM_LEN];
    u32 daddr;
    u16 dport;
    u16 sport;
};

// Trace tcp_sendmsg: arg0=struct sock*, arg1=size
int trace_tcp_sendmsg(struct pt_regs *ctx) {
    struct sock *sk = (struct sock *)PT_REGS_PARM1(ctx);
    int size = (int)PT_REGS_PARM2(ctx);
    if (size <= 0) return 0;

    u64 key = (u64)sk;
    struct byte_count *val = byte_map.lookup(&key);

    if (val) {
        val->sent += size;
    } else {
        struct byte_count new = {};
        new.sent = size;
        new.pid = bpf_get_current_pid_tgid() >> 32;
        bpf_get_current_comm(&new.comm, sizeof(new.comm));

        struct inet_sock *inet = (struct inet_sock *)sk;
        new.daddr = inet->inet_daddr;
        new.dport = inet->inet_dport;
        new.sport = inet->inet_sport;

        byte_map.update(&key, &new);
    }

    return 0;
}

// Trace tcp_cleanup_rbuf: arg0=struct sock*, arg1=copied
int trace_tcp_cleanup_rbuf(struct pt_regs *ctx) {
    struct sock *sk = (struct sock *)PT_REGS_PARM1(ctx);
    int copied = (int)PT_REGS_PARM2(ctx);
    if (copied <= 0) return 0;

    u64 key = (u64)sk;
    struct byte_count *val = byte_map.lookup(&key);

    if (val) {
        val->recv += copied;
    } else {
        struct byte_count new = {};
        new.recv = copied;
        new.pid = bpf_get_current_pid_tgid() >> 32;
        bpf_get_current_comm(&new.comm, sizeof(new.comm));

        struct inet_sock *inet = (struct inet_sock *)sk;
        new.daddr = inet->inet_daddr;
        new.dport = inet->inet_dport;
        new.sport = inet->inet_sport;

        byte_map.update(&key, &new);
    }

    return 0;
}
"""


class EbpfByteTracker:
    """eBPF-based per-PID, per-connection byte tracker.

    Falls back to a no-op passthrough if bcc is unavailable
    or if the kernel does not support the required probes.
    """

    def __init__(self) -> None:
        self._bpf: Optional[BPF] = None
        self._available = False
        self._error: Optional[str] = None
        self._samples: List[EbpfByteSample] = []
        self._lock = threading.Lock()
        self._setup()

    def _setup(self) -> None:
        """Try to load and attach the eBPF program."""
        if not _BCC_AVAILABLE:
            self._error = "bcc Python module not installed"
            logger.info(
                "eBPF: bcc module not available — using poll-based fallback"
            )
            return

        try:
            # Check kernel version / capabilities
            if not os.path.exists("/sys/kernel/btf/vmlinux"):
                logger.debug("eBPF: BTF not available; trying legacy kprobe path")

            self._bpf = BPF(text=BPF_PROGRAM)

            # Attach kprobes
            try:
                self._bpf.attach_kprobe(
                    event="tcp_sendmsg", fn_name="trace_tcp_sendmsg"
                )
            except Exception as exc:
                logger.warning(
                    "eBPF: cannot attach tcp_sendmsg kprobe: %s", exc
                )
                self._bpf = None
                self._error = str(exc)
                return

            try:
                self._bpf.attach_kprobe(
                    event="tcp_cleanup_rbuf", fn_name="trace_tcp_cleanup_rbuf"
                )
            except Exception as exc:
                logger.warning(
                    "eBPF: cannot attach tcp_cleanup_rbuf kprobe: %s", exc
                )
                # Partial attachment — still usable for sent bytes
                logger.info("eBPF: operating with tcp_sendmsg only (sent bytes)")

            self._available = True
            logger.info(
                "eBPF byte tracker active — accurate per-PID byte accounting"
            )

        except Exception as exc:
            self._error = str(exc)
            logger.warning(
                "eBPF: cannot load BPF program: %s", exc
            )
            logger.info("eBPF: falling back to poll-based conntrack")

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def error(self) -> Optional[str]:
        return self._error

    def read_and_reset(self) -> List[EbpfByteSample]:
        """Read accumulated byte counters from the eBPF map and reset them.

        Returns a list of EbpfByteSample objects with per-connection byte totals.
        Each call atomically reads and clears the map.
        """
        if not self._available or self._bpf is None:
            return []

        samples: List[EbpfByteSample] = []
        byte_map = self._bpf.get_table("byte_map")

        try:
            for key, val in byte_map.items():
                try:
                    # Parse daddr (32-bit BE IP)
                    daddr_int = val.daddr.value if hasattr(val.daddr, 'value') else val.daddr
                    daddr_str = _ip_to_str(daddr_int)

                    sample = EbpfByteSample(
                        pid=val.pid.value if hasattr(val.pid, 'value') else val.pid,
                        comm=(
                            val.comm.value.decode("utf-8", errors="replace")
                            if hasattr(val.comm, 'value')
                            else val.comm.decode("utf-8", errors="replace")
                        ),
                        daddr=daddr_str,
                        dport=socket.ntohs(
                            val.dport.value if hasattr(val.dport, 'value') else val.dport
                        ),
                        sport=socket.ntohs(
                            val.sport.value if hasattr(val.sport, 'value') else val.sport
                        ),
                        bytes_sent=val.sent.value if hasattr(val.sent, 'value') else val.sent,
                        bytes_recv=val.recv.value if hasattr(val.recv, 'value') else val.recv,
                    )
                    samples.append(sample)
                except Exception:
                    continue

            # Clear the map for next interval
            byte_map.clear()
        except Exception as exc:
            logger.debug("eBPF: error reading byte map: %s", exc)

        return samples

    def cleanup(self) -> None:
        """Detach kprobes and release resources."""
        if self._bpf is not None:
            try:
                self._bpf.detach_kprobe(event="tcp_sendmsg")
                self._bpf.detach_kprobe(event="tcp_cleanup_rbuf")
            except Exception:
                pass
            self._bpf = None
            self._available = False


def _ip_to_str(ip_int: int) -> str:
    """Convert a 32-bit integer to an IPv4 dotted string.

    The value from eBPF is stored as-is from inet_daddr (__be32).
    We unpack it as network-byte-order bytes.
    """
    import struct

    raw = struct.pack(">I", ip_int & 0xFFFFFFFF)
    return ".".join(str(b) for b in raw)


# ── Availability check ─────────────────────────────────────────────

def is_bcc_available() -> tuple[bool, str]:
    """Check if the eBPF/bcc path is available.

    Returns (available: bool, message: str).
    """
    if not _BCC_AVAILABLE:
        return False, "bcc Python module not installed (pip install bcc)"
    try:
        # Quick test: can we create a minimal BPF object?
        test = BPF(text="int kprobe__sys_clone(void *ctx) { return 0; }")
        test.cleanup()
        return True, "eBPF via bcc"
    except Exception as exc:
        return False, f"eBPF BPF program load failed: {exc}"


# Connection-level byte tracker that integrates with FlowWriter
class EbpfFlowTracker:
    """Integrates eBPF byte samples with the FlowWriter.

    Tracks per-flow byte deltas between poll cycles.
    """

    def __init__(self) -> None:
        self._ebpf = EbpfByteTracker()

    @property
    def available(self) -> bool:
        return self._ebpf.is_available

    @property
    def capture_method(self) -> str:
        if self._ebpf.is_available:
            return "eBPF (bcc) — tcp_sendmsg + tcp_cleanup_rbuf"
        cause = self._ebpf.error or "unavailable"
        return f"Poll-based (conntrack) — eBPF fallback: {cause}"

    def get_byte_deltas(
        self,
    ) -> Dict[Tuple[str, int, int], Tuple[int, int]]:
        """Read eBPF byte counters and return per-connection deltas.

        Returns dict keyed by (process_name, daddr, dport) →
        (bytes_sent_delta, bytes_recv_delta).

        If eBPF is unavailable, returns empty dict (caller falls back
        to conntrack).
        """
        deltas: Dict[Tuple[str, int, int], Tuple[int, int]] = {}
        if not self._ebpf.is_available:
            return deltas

        samples = self._ebpf.read_and_reset()
        for s in samples:
            key = (s.comm, s.daddr, s.dport)
            existing = deltas.get(key, (0, 0))
            deltas[key] = (
                existing[0] + s.bytes_sent,
                existing[1] + s.bytes_recv,
            )

        return deltas

    def cleanup(self) -> None:
        self._ebpf.cleanup()
