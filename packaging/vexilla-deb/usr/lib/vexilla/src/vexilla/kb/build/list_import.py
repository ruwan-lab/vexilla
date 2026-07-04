"""List importer — reads public domain lists and merges them for KB build.

Run by maintainers to import StevenBlack, EasyList, and Tranco lists.
Produces a deduplicated, categorized domain set that feeds into pipeline.py.

Usage:
    python -m vexilla.kb.build.list_import <list_file> --category advertising
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Regex to extract domain from host file lines like:
#   0.0.0.0 doubleclick.net
_HOSTS_LINE = re.compile(r"^(?:0\.0\.0\.0|127\.0\.0\.1)\s+(\S+)")


def parse_hosts_file(path: Path) -> list[str]:
    """Parse a hosts-file format blocklist and return domains."""
    domains: list[str] = []
    try:
        text = path.read_text()
    except FileNotFoundError:
        logger.warning("File not found: %s", path)
        return domains

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _HOSTS_LINE.match(line)
        if m:
            domain = m.group(1).lower()
            # Remove trailing dots
            domain = domain.rstrip(".")
            if domain and "." in domain:  # must be a real domain
                domains.append(domain)

    logger.info("Parsed %d domains from %s", len(domains), path.name)
    return domains


def parse_easylist(path: Path) -> list[str]:
    """Parse EasyList format and extract domains.

    Handles lines like:
        ||doubleclick.net^
        ||ads.example.com^$third-party
    """
    domains: list[str] = []
    try:
        text = path.read_text()
    except FileNotFoundError:
        logger.warning("File not found: %s", path)
        return domains

    pattern = re.compile(r"^\|\|([a-zA-Z0-9._-]+)\^")

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("!"):
            continue
        m = pattern.match(line)
        if m:
            domain = m.group(1).lower()
            if domain and "." in domain:
                domains.append(domain)

    logger.info("Parsed %d domains from %s", len(domains), path.name)
    return domains


def parse_tranco(path: Path, limit: int = 10000) -> list[str]:
    """Parse Tranco top-sites list and return domains.

    Format: rank,domain
    """
    domains: list[str] = []
    try:
        text = path.read_text()
    except FileNotFoundError:
        logger.warning("File not found: %s", path)
        return domains

    for i, line in enumerate(text.splitlines()):
        if i >= limit:
            break
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) >= 2:
            domain = parts[1].strip().lower()
            if domain and "." in domain:
                domains.append(domain)

    logger.info("Parsed %d domains from %s (limit=%d)", len(domains), path.name, limit)
    return domains


def deduplicate(domains: list[str]) -> list[str]:
    """Remove duplicates while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return result
