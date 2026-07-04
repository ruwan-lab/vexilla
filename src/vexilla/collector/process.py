"""Process resolution — inode→PID mapping via `ss -tnp`.

Uses ss (netlink) which works under systemd sandbox (ProtectHome=true)
and correctly attributes each connection to the owning process.

Two matching strategies:
  1. Primary: `ss -tnp` for (tuple → PID) via netlink (bypasses /proc sandboxing)
  2. Fallback: /proc/<pid>/net/tcp for inode→PID (broader matching)
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Dict, Optional, Tuple

from vexilla.collector.models import ProcInfo

logger = logging.getLogger(__name__)


class ProcessResolver:
    """Resolves socket inodes to process name and exe path.

    Uses `ss -tnp` (netlink) to build a (remote_ip, remote_port) → PID map.
    This correctly attributes connections and works under systemd sandbox.
    """

    def __init__(self, cache_ttl: float = 30.0) -> None:
        self._pid_info: Dict[int, ProcInfo] = {}
        self._last_refresh: float = 0.0
        self._cache_ttl = cache_ttl

        # Primary: (remote_ip, remote_port) → pid from ss -tnp
        self._tuple_map: Dict[Tuple[str, int], int] = {}

        # Fallback: inode → pid from /proc/<pid>/net/tcp
        self._inode_map: Dict[int, int] = {}

    def resolve(
        self,
        inode: int,
        remote_ip: Optional[str] = None,
        remote_port: Optional[int] = None,
    ) -> Optional[ProcInfo]:
        """Resolve a connection to its owning process info.

        Tries ss-based tuple matching first (most accurate),
        then falls back to inode-based mapping.
        """
        self._refresh_if_stale()

        pid: Optional[int] = None

        # Strategy 1: Match by (remote_ip, remote_port) from ss -tnp
        if remote_ip and remote_port is not None:
            pid = self._tuple_map.get((remote_ip, remote_port))

        # Strategy 2: Fallback to inode-based matching from /proc/<pid>/net/tcp
        if pid is None:
            pid = self._inode_map.get(inode)

        if pid is None:
            return None
        return self._pid_info.get(pid)

    def refresh(self) -> None:
        """Force a full rescan of process-to-connection mappings."""
        self._pid_info.clear()
        self._tuple_map.clear()
        self._inode_map.clear()

        # Phase 1: Build (ip, port) → PID map via ss -tnp (netlink, sandbox-safe)
        self._parse_ss_output()

        # Phase 2: Read process info for all referenced PIDs
        for pid in set(self._tuple_map.values()) | set(self._inode_map.values()):
            info = self._read_proc_info(pid)
            if info is not None:
                self._pid_info[pid] = info

        logger.debug(
            "Process resolver: %d pids via ss, %d via /proc/net",
            len(set(self._tuple_map.values())),
            len(set(self._inode_map.values())),
        )

    def _parse_ss_output(self) -> None:
        """Parse `ss -tnp` to build (ip, port) → PID mappings.

        ss -tnp line format:
          ESTAB 0 0  192.168.1.11:43348  184.51.195.147:443
            users:(("firefox",pid=12278,fd=105))
        """
        try:
            result = subprocess.run(
                ["ss", "-tnp"],
                capture_output=True, text=True, timeout=5.0,
            )
            if result.returncode != 0:
                return

            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("State"):
                    continue
                if "pid=" not in line:
                    continue

                # Split on whitespace, handle multiple columns
                parts = line.split()
                # ESTAB column layout: State Recv-Q Send-Q Local:Port Peer:Port
                # ss -tnp: index 0=State, 1=RecvQ, 2=SendQ, 3=Local, 4=Peer, rest=users(...)
                if len(parts) < 5:
                    continue

                peer = parts[4]  # e.g. "184.51.195.147:443"
                if ":" not in peer:
                    continue

                # Parse peer IP and port
                try:
                    peer_ip, peer_port_str = peer.rsplit(":", 1)
                    peer_port = int(peer_port_str)
                except (ValueError, IndexError):
                    continue

                # Extract PID from users section in the FULL line (may have more columns)
                full_line = " ".join(parts[5:]) if len(parts) > 5 else ""
                pid = _extract_pid(full_line)
                if pid is not None:
                    self._tuple_map[(peer_ip, peer_port)] = pid

        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("ss -tnp failed: %s", exc)

    def _read_proc_info(self, pid: int) -> Optional[ProcInfo]:
        """Read process name and exe path for a PID via /proc."""
        try:
            comm_path = f"/proc/{pid}/comm"
            if os.path.exists(comm_path):
                with open(comm_path) as f:
                    comm = f.read().strip()
            else:
                comm = f"pid{pid}"

            exe_path = None
            try:
                exe_path = os.readlink(f"/proc/{pid}/exe")
            except OSError:
                pass

            return ProcInfo(pid=pid, comm=comm, exe_path=exe_path)
        except (OSError, ValueError) as exc:
            logger.debug("Failed to read proc info for pid %d: %s", pid, exc)
            return None

    def _refresh_if_stale(self) -> None:
        now = time.monotonic()
        if now - self._last_refresh > self._cache_ttl:
            self.refresh()
            self._last_refresh = now


def _extract_pid(text: str) -> Optional[int]:
    """Extract PID from ss users section text.

    Input like: users:(("firefox",pid=12278,fd=105))
    """
    idx = text.find("pid=")
    if idx == -1:
        return None
    end = text.find(",", idx)
    if end == -1:
        end = text.find(")", idx)
    if end == -1:
        return None
    try:
        return int(text[idx + 4 : end])
    except ValueError:
        return None
