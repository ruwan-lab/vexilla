"""Process resolution — inode→PID mapping via /proc/<pid>/net/tcp.

Alternative to scanning /proc/<pid>/fd/ which can fail under systemd's
ProtectHome=true sandbox. Reads /proc/<pid>/net/tcp which directly
lists socket inodes per process.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional

from vexilla.collector.models import ProcInfo

logger = logging.getLogger(__name__)


class ProcessResolver:
    """Resolves socket inodes to process name and exe path.

    Maintains a cache of inode→PID mappings refreshed on demand.
    Uses /proc/<pid>/net/tcp which works under systemd sandbox.
    """

    def __init__(self, cache_ttl: float = 30.0) -> None:
        self._inode_map: Dict[int, int] = {}
        self._pid_info: Dict[int, ProcInfo] = {}
        self._last_refresh: float = 0.0
        self._cache_ttl = cache_ttl

    def resolve(self, inode: int) -> Optional[ProcInfo]:
        """Resolve a socket inode to its owning process info."""
        self._refresh_if_stale()
        pid = self._inode_map.get(inode)
        if pid is None:
            return None
        return self._pid_info.get(pid)

    def refresh(self) -> None:
        """Force a full rescan of inode→PID mappings.

        Reads /proc/<pid>/net/tcp for each process to find socket inodes,
        plus /proc/<pid>/comm and /proc/<pid>/exe for process info.
        """
        self._inode_map.clear()
        self._pid_info.clear()

        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)

            try:
                # Read process info first
                comm = self._read_comm(pid)
                exe_path = self._read_exe(pid)
                if comm is None:
                    continue

                self._pid_info[pid] = ProcInfo(
                    pid=pid, comm=comm, exe_path=exe_path,
                )

                # Read /proc/<pid>/net/tcp for this process's socket inodes
                tcp_file = f"/proc/{pid}/net/tcp"
                if not os.path.exists(tcp_file):
                    continue

                try:
                    with open(tcp_file) as f:
                        for line in f:
                            if line.startswith("sl"):
                                continue  # header
                            parts = line.split()
                            if len(parts) >= 10:
                                try:
                                    inode = int(parts[9])
                                    if inode > 0:
                                        self._inode_map[inode] = pid
                                except (ValueError, IndexError):
                                    pass
                except (OSError, ValueError, IndexError):
                    continue

            except (OSError, ValueError):
                continue

        logger.debug(
            "Process resolver: %d pids, %d sockets",
            len(self._pid_info), len(self._inode_map),
        )

    def _read_comm(self, pid: int) -> Optional[str]:
        """Read process command name from /proc/<pid>/comm."""
        try:
            with open(f"/proc/{pid}/comm") as f:
                return f.read().strip()
        except OSError:
            return None

    def _read_exe(self, pid: int) -> Optional[str]:
        """Read process exe path from /proc/<pid>/exe."""
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None

    def _refresh_if_stale(self) -> None:
        now = time.monotonic()
        if now - self._last_refresh > self._cache_ttl:
            self.refresh()
            self._last_refresh = now
