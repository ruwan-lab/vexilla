"""Active/background classification — multi-signal heuristic.

Classification flow (first match wins):
  1. Display server foreground check (X11 _NET_ACTIVE_WINDOW)
  2. Root / system user check
  3. Cgroup check (system.slice → background)
  4. Known daemon name check
  5. TTY check (no controlling TTY → likely background)
  6. Known interactive app check
  7. System binary path check
  8. Default: active (conservative — don't alarm on unknowns)

Each branch records its evidence string for explainability.
All signals are optional — failures degrade gracefully.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

PROCFS = Path("/proc")

# ── Display server: cache the active-window PID ──────────────────
_ACTIVE_PID: Optional[int] = None
_ACTIVE_PID_TIME: float = 0.0
_ACTIVE_PID_TTL: float = 2.0  # refresh every 2 seconds


def _get_active_window_pid_via_x11() -> Optional[int]:
    """Return the PID of the currently focused X11 window, or None.

    Uses _NET_ACTIVE_WINDOW via xprop. Falls back cleanly if unavailable.
    """
    global _ACTIVE_PID, _ACTIVE_PID_TIME
    now = time.monotonic()
    if now - _ACTIVE_PID_TIME < _ACTIVE_PID_TTL:
        return _ACTIVE_PID  # cached

    _ACTIVE_PID = None
    _ACTIVE_PID_TIME = now
    try:
        # Get active window ID
        result = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            capture_output=True, text=True, timeout=1.0,
        )
        if result.returncode != 0:
            return None
        # Parse: "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x..."
        for token in result.stdout.split():
            if token.startswith("0x"):
                window_id = token
                break
        else:
            return None

        # Get PID of the active window
        result2 = subprocess.run(
            ["xprop", "-id", window_id, "_NET_WM_PID"],
            capture_output=True, text=True, timeout=1.0,
        )
        if result2.returncode != 0:
            return None
        # Parse: "_NET_WM_PID(CARDINAL): 1234"
        parts = result2.stdout.strip().split()
        if parts:
            pid_str = parts[-1]
            if pid_str.isdigit():
                _ACTIVE_PID = int(pid_str)
                return _ACTIVE_PID
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _get_foreground_pid_via_wayland() -> Optional[int]:
    """Return the PID of the foreground app via Wayland protocols.

    Tries sway's get_tree for compositors that support it.
    """
    import json  # local import; used in except handler

    try:
        result = subprocess.run(
            ["swaymsg", "-t", "get_tree", "--raw"],
            capture_output=True, text=True, timeout=1.0,
        )
        if result.returncode == 0:
            tree = json.loads(result.stdout)
            return _find_focused_pid(tree)
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired, OSError):
        pass

    # Try hyprctl for Hyprland
    try:
        result = subprocess.run(
            ["hyprctl", "activewindow", "-j"],
            capture_output=True, text=True, timeout=1.0,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("pid")
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired, OSError):
        pass

    return None


def _find_focused_pid(node: dict) -> Optional[int]:
    """Recursively search a sway node tree for the focused leaf's PID."""
    if node.get("focused"):
        pid = node.get("pid")
        if pid and pid > 0:
            return pid
    for child in node.get("nodes", []):
        result = _find_focused_pid(child)
        if result:
            return result
    for child in node.get("floating_nodes", []):
        result = _find_focused_pid(child)
        if result:
            return result
    return None


def _get_foreground_pid() -> Optional[int]:
    """Return the PID of the foreground app, or None.

    Tries X11 first, then Wayland compositors.
    """
    pid = _get_active_window_pid_via_x11()
    if pid is not None:
        return pid
    pid = _get_foreground_pid_via_wayland()
    if pid is not None:
        return pid
    return None


# ── Cgroup check ─────────────────────────────────────────────────

def _in_system_cgroup(pid: int) -> bool:
    """Check if a process is in a system cgroup (background)."""
    try:
        text = (PROCFS / str(pid) / "cgroup").read_text()
        return "system.slice" in text or "systemd" in text
    except (OSError, FileNotFoundError):
        return False


def _has_controlling_tty(pid: int) -> bool:
    """Check if a process has a controlling terminal (active)."""
    try:
        stat = (PROCFS / str(pid) / "stat").read_text()
        # Field 7 (0-indexed field 6) = tty_nr
        # Format: "pid (comm) S ... tty_nr ..."
        # Parentheses in comm make it tricky; find the closing ')'
        end_paren = stat.rfind(")")
        if end_paren < 0:
            return False
        fields = stat[end_paren + 2:].split()
        if len(fields) >= 5:
            tty_nr = fields[4]  # field index 4 after the state field
            return tty_nr != "0"
        return False
    except (OSError, FileNotFoundError, IndexError, ValueError):
        return False


# ── Expanded app sets ─────────────────────────────────────────────

_INTERACTIVE_APPS = {
    # Browsers
    "firefox", "firefox-esr", "chrome", "chromium", "chromium-browser",
    "brave", "brave-browser", "opera", "edge", "microsoft-edge",
    "vivaldi", "tor", "tor-browser", "torbrowser",
    # Mail / Calendar
    "thunderbird", "evolution", "geary", "mailspring", "protonmail-bridge",
    "kmail", "kontact",
    # Chat / Communication
    "slack", "discord", "telegram", "telegram-desktop", "signal-desktop",
    "whatsapp-desktop", "element-desktop", "riot-desktop",
    "fractal", "hexchat", "irssi", "weechat",
    # Video calls
    "zoom", "teams", "webex", "skype", "skypeforlinux",
    "google-chat", "meet",
    # Media
    "spotify", "rhythmbox", "clementine", "audacious", "vlc", "mpv",
    "strawberry", "deadbeef", "cmus",
    # Terminals
    "gnome-terminal", "konsole", "alacritty", "kitty", "terminator",
    "tilix", "urxvt", "xterm", "st", "foot", "wezterm",
    # Development
    "code", "code-oss", "codium", "idea", "pycharm", "eclipse",
    "webstorm", "clion", "goland", "intellij", "android-studio",
    "sublime_text", "atom", "gedit", "vim", "nvim", "neovim",
    "emacs", "emacs-x", "vim.gtk3",
    # Office / Productivity
    "libreoffice", "soffice.bin", "evince", "okular", "zathura",
    "onlyoffice", "wps-office",
    # Graphics / Design
    "gimp", "inkscape", "krita", "blender", "darktable",
    "shotwell", "eog", "gthumb",
    # Games
    "steam", "steam-webhelper", "lutris",
}

_BACKGROUND_APPS = {
    # System init / service managers
    "systemd", "systemd-resolved", "systemd-network", "systemd-timesyncd",
    "systemd-journald", "systemd-logind", "systemd-udevd",
    # Network
    "NetworkManager", "dhclient", "dhcpcd", "netplan", "wpa_supplicant",
    "avahi-daemon", "dnsmasq", "unbound",
    # Printing
    "cupsd", "cups-browsed", "cups-notifier",
    # Package management
    "snapd", "apt", "dpkg", "dpkg-query", "unattended-upgrades",
    "packagekitd", "packagekit", "snapd.session-agent",
    # Time
    "chronyd", "ntpd", "ntpdate", "timesyncd",
    # SSH / Remote
    "sshd", "sshd-agent", "dropbear",
    # Logging
    "rsyslogd", "syslogd", "syslog-ng", "journald",
    # D-Bus
    "dbus-daemon", "dbus-broker", "dbus-launch",
    # Auth / Polkit
    "polkitd", "accounts-daemon", "pam-auth-update",
    # Power / Hardware
    "upowerd", "thermald", "power-profiles-daemon", "fwupd",
    # Containers
    "containerd", "containerd-shim", "dockerd", "docker-proxy",
    "podman", "crio", "kubelet",
    # Audio
    "pipewire", "wireplumber", "pulseaudio", "pulseaudio-rtp",
    "alsactl", "rtkitctl",
    # Display / Login
    "gdm", "gdm3", "sddm", "lightdm", "xdm",
    "loginwindow", "session-watchdog",
    # Security
    "clamd", "freshclam", "ufw", "firewalld", "apparmor",
    # Desktop services
    "gsd-*", "gnome-settings-daemon", "kdeinit5",
    "xdg-document-portal", "xdg-permission-store",
    # Mail / Messaging background services
    "msmdsrv", "msmtp",
}

# Desktop file categories for GUI app detection
_GUI_CATEGORIES = {
    "GNOME", "GTK", "Qt", "KDE", "Xfce", "Toolkit",
    "Browser", "Mail", "Chat", "Media", "Development",
    "Office", "Graphics", "Game", "Audio", "Video",
}


def _check_gui_desktop_file(pid: int) -> Optional[str]:
    """Check if a process's desktop file suggests it's an interactive GUI app.

    Reads /proc/<pid>/environ for DISPLAY/WAYLAND_DISPLAY and checks
    /proc/<pid>/cwd for desktop files.
    """
    try:
        environ_path = PROCFS / str(pid) / "environ"
        env_data = environ_path.read_bytes()
        env_str = env_data.decode("utf-8", errors="replace")
        if "DISPLAY" in env_str or "WAYLAND_DISPLAY" in env_str:
            return "has display server environment variables"
    except (OSError, FileNotFoundError):
        pass
    return None


def _has_display_env(pid: int) -> bool:
    """Check if a process has display server access (active signal)."""
    try:
        env_data = (PROCFS / str(pid) / "environ").read_bytes()
        env_str = env_data.decode("utf-8", errors="replace")
        return "DISPLAY=" in env_str or "WAYLAND_DISPLAY=" in env_str
    except (OSError, FileNotFoundError):
        return False


# ═══════════════════════════════════════════════════════════════════
# Main classify function
# ═══════════════════════════════════════════════════════════════════


def classify(comm: str, exe_path: str | None, uid: int, pid: int = 0) -> Tuple[int, str]:
    """Classify a process as background (1) or active (0).

    Uses multiple signals in order of reliability. First match wins.
    Returns (is_background: int, evidence: str).

    Args:
        comm: Process short name (/proc/pid/comm).
        exe_path: Full executable path (/proc/pid/exe).
        uid: User ID (0 = root).
        pid: Process ID. Required for display server and cgroup checks.
    """
    name = comm.lower()

    # ── 1. Display server: is this the foreground app? ─────────────
    if pid > 0:
        foreground_pid = _get_foreground_pid()
        if foreground_pid is not None and foreground_pid == pid:
            return 0, f"foreground app on display server (pid {pid})"

    # ── 2. Root / system user ──────────────────────────────────────
    if uid == 0:
        return 1, f"root process ({name})"
    if uid < 1000 and uid > 0:
        return 1, f"system user (uid {uid})"

    # ── 3. Cgroup check ────────────────────────────────────────────
    if pid > 0 and _in_system_cgroup(pid):
        return 1, f"system cgroup ({name})"

    # ── 4. Known background apps ───────────────────────────────────
    if name in _BACKGROUND_APPS:
        return 1, f"known system daemon ({name})"

    # ── 5. TTY check: no controlling terminal → likely daemon ──────
    if pid > 0 and not _has_controlling_tty(pid):
        # Don't immediately mark as background — check display env first
        if not _has_display_env(pid):
            return 1, f"no tty and no display ({name})"

    # ── 6. Known interactive apps ─────────────────────────────────
    if name in _INTERACTIVE_APPS:
        return 0, f"known interactive app ({name})"

    # ── 7. Display environment: has DISPLAY but unknown app ────────
    if pid > 0 and _has_display_env(pid):
        return 0, f"has display environment ({name})"

    # ── 8. System binary path ──────────────────────────────────────
    if exe_path:
        exe_lower = exe_path.lower()
        if exe_lower.startswith("/usr/sbin/") or exe_lower.startswith("/sbin/"):
            return 1, f"system binary path ({exe_path})"

    # ── 9. Default: active (conservative) ──────────────────────────
    return 0, f"unknown process, default active ({name})"
