"""Process resolution — inode→PID mapping via /proc/<pid>/fd/*.

Reused techniques (not code) from OpenSnitch/Portmaster — simple directory
scanning, well-understood on Linux.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional

from vexilla.collector.models import ProcInfo

logger = logging.getLogger(__name__)

PROCFS = Path("/proc")


class ProcessResolver:
    """Resolves socket inodes to process name and exe path.

    Maintains a cache of inode→PID mappings refreshed on demand.
    """

    def __init__(self, cache_ttl: float = 30.0) -> None:
        self._inode_map: Dict[int, int] = {}  # inode → pid
        self._pid_info: Dict[int, ProcInfo] = {}  # pid → ProcInfo
        self._last_refresh: float = 0.0
        self._cache_ttl = cache_ttl

    def resolve(self, inode: int) -> Optional[ProcInfo]:
        """Resolve a socket inode to its owning process info.

        Returns None if the inode cannot be resolved (process exited).
        """
        self._refresh_if_stale()
        pid = self._inode_map.get(inode)
        if pid is None:
            return None
        info = self._pid_info.get(pid)
        if info is None:
            return None
        return info

    def refresh(self) -> None:
        """Force a full rescan of inode→PID mappings."""
        self._inode_map.clear()
        self._pid_info.clear()

        try:
            for proc_dir in PROCFS.iterdir():
                if not proc_dir.name.isdigit():
                    continue
                pid = int(proc_dir.name)
                pid_info = self._read_proc_info(pid)
                if pid_info is None:
                    continue

                self._pid_info[pid] = pid_info

                # Scan fd/ directory for socket:[inode] symlinks
                fd_dir = proc_dir / "fd"
                if not fd_dir.is_dir():
                    continue
                try:
                    for fd_entry in fd_dir.iterdir():
                        try:
                            link = os.readlink(str(fd_entry))
                            if link.startswith("socket:["):
                                inode_str = link[8:-1]  # strip 'socket:[' and ']'
                                inode = int(inode_str)
                                self._inode_map[inode] = pid
                        except (OSError, ValueError):
                            pass
                except PermissionError:
                    # Normal for processes owned by other users
                    pass
                except OSError as exc:
                    logger.debug("Error scanning fd dir for pid %d: %s", pid, exc)

            logger.debug(
                "Process resolver refreshed: %d pids, %d sockets",
                len(self._pid_info),
                len(self._inode_map),
            )
        except PermissionError:
            logger.warning("Cannot read /proc — running with sufficient permissions?")

    def _read_proc_info(self, pid: int) -> Optional[ProcInfo]:
        """Read process name and exe path for a PID."""
        try:
            comm_path = PROCFS / str(pid) / "comm"
            if comm_path.exists():
                comm = comm_path.read_text().strip()
            else:
                comm = f"pid{pid}"

            exe_path = None
            try:
                exe = os.readlink(str(PROCFS / str(pid) / "exe"))
                if exe:
                    exe_path = exe
            except OSError:
                pass

            return ProcInfo(pid=pid, comm=comm, exe_path=exe_path)
        except (OSError, ValueError) as exc:
            logger.debug("Failed to read proc info for pid %d: %s", pid, exc)
            return None

    def _refresh_if_stale(self) -> None:
        if time.monotonic() - self._last_refresh > self._cache_ttl:
            self.refresh()
            self._last_refresh = time.monotonic()
