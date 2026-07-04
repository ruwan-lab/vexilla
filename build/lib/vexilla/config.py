"""Configuration — all defaults, all overridable via config file or env vars.

Dev-mode default paths (no root required):
    DB:          ~/.local/share/vexilla/vexilla.db
    KB:          resolved from package data at runtime
    Config:      ~/.config/vexilla/config.toml

Production paths (Phase 6) swap these to /var/lib, /usr/share, /etc.
"""

from __future__ import annotations

import os
import sys
import tomllib
import logging
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _user_home() -> Path:
    """Return the original user's home directory, even when running via sudo."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            import pwd
            return Path(pwd.getpwnam(sudo_user).pw_dir)
        except (ImportError, KeyError):
            pass
    return Path.home()


def _kb_path_default() -> Path:
    """Resolve kb.db from package data.

    Tries in order:
    1. data/kb.db alongside the package (development / editable install)
    2. Site-packages bundled data (installed via pip)
    3. ~/.local/share/vexilla/kb.db (user data dir)
    """
    # Development: relative to project root
    dev_path = Path(__file__).resolve().parent.parent.parent / "data" / "kb.db"
    if dev_path.exists():
        return dev_path

    # Production: alongside package data
    pkg_path = Path(__file__).resolve().parent.parent / "data" / "kb.db"
    if pkg_path.exists():
        return pkg_path

    # Fallback: user data directory
    return _data_dir() / "kb.db"


def _data_dir() -> Path:
    return _user_home() / ".local" / "share" / "vexilla"


def _config_dir() -> Path:
    return _user_home() / ".config" / "vexilla"


def _config_path() -> Path:
    return _config_dir() / "config.toml"


class Settings(BaseSettings):
    # ── Paths ──────────────────────────────────────────────────────────
    db_path: Path = Field(default_factory=lambda: _data_dir() / "vexilla.db")
    kb_path: Path = Field(default_factory=_kb_path_default)

    # ── Network ────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = 8787

    # ── Collector ──────────────────────────────────────────────────────
    poll_interval_s: float = 2.0
    insight_interval_s: float = 60.0

    # ── Retention ──────────────────────────────────────────────────────
    retention_days: int = 30

    # ── Behaviour ──────────────────────────────────────────────────────
    log_level: str = "INFO"
    consent_required: bool = True

    model_config = SettingsConfigDict(
        env_prefix="VEXILLA_",
        env_file=".env",
        extra="ignore",
    )

    @classmethod
    def load(cls) -> "Settings":
        """Load settings, merging defaults with optional config file."""
        cfg_path = _config_path()
        overrides: dict = {}
        if cfg_path.exists():
            with cfg_path.open("rb") as fh:
                overrides = tomllib.load(fh)
            logger.info("Loaded config overrides from %s", cfg_path)
        return cls(**overrides)

    def ensure_dirs(self) -> None:
        """Create data & config directories if missing."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        _config_dir().mkdir(parents=True, exist_ok=True)
