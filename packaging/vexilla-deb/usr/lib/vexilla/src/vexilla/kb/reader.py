"""Offline knowledge base reader — looks up domains in kb.db.

Implements the lookup chain:
    exact domain → alias table → registrable-domain fallback → unrecognized

At runtime there are zero network calls and zero LLM calls (ADR-0003).
kb.db is shipped read-only with the app.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Categories from insight-engine.md
CATEGORIES = {
    "essential",
    "os_update",
    "cdn",
    "cloud_infra",
    "advertising",
    "tracker_analytics",
    "telemetry",
    "social",
    "media_streaming",
    "messaging",
    "unrecognized",
}

_HUMAN_CATEGORY = {
    "essential": "essential service",
    "os_update": "operating system update",
    "cdn": "content delivery network",
    "cloud_infra": "cloud infrastructure",
    "advertising": "advertising / tracking",
    "tracker_analytics": "tracker / analytics",
    "telemetry": "telemetry / usage reporting",
    "social": "social media",
    "media_streaming": "media / streaming",
    "messaging": "messaging",
    "unrecognized": "unrecognized service",
}


@dataclass
class DomainInfo:
    """Information about a domain from the knowledge base."""

    domain: str
    owner: Optional[str]
    category: str
    category_human: str
    purpose_plain: Optional[str]
    privacy_note: Optional[str]
    suggestion: Optional[str]
    confidence: str
    kb_hit: bool  # True if found in kb.db, False if fallback


def _registrable(domain: str) -> str:
    """Extract the registrable domain (simplified: last two labels)."""
    parts = domain.rsplit(".", 2)
    if len(parts) >= 2:
        return parts[-2] + "." + parts[-1]
    return domain



class KbReader:
    """Read-only knowledge base domain lookups.

    Opens kb.db if available; falls back to 'unrecognized' for all lookups.
    """

    def __init__(self, kb_path: Optional[Path | str] = None) -> None:
        if isinstance(kb_path, str):
            kb_path = Path(kb_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._available = False

        if kb_path is not None and kb_path.exists():
            try:
                self._conn = sqlite3.connect(str(kb_path), uri=True)
                self._conn.execute("PRAGMA query_only = ON;")
                self._available = True
                # Check minimal schema
                row = self._conn.execute(
                    "SELECT COUNT(*) FROM kb_domain"
                ).fetchone()
                count = row[0] if row else 0
                logger.info(
                    "KB loaded: %s (%d domains)", kb_path, count
                )
            except Exception as exc:
                logger.warning("Cannot open KB at %s: %s", kb_path, exc)

    @property
    def is_available(self) -> bool:
        return self._available

    def lookup(self, domain: str) -> DomainInfo:
        """Look up a domain, following the fallback chain.

        Returns DomainInfo — always a result, never None.
        If the domain is unknown, category='unrecognized', kb_hit=False.
        """
        if not self._available or self._conn is None:
            return self._unknown(domain)

        # Step 1: exact match
        info = self._query_domain(domain)
        if info is not None:
            return info

        # Step 2: alias table
        alias_row = self._conn.execute(
            "SELECT domain FROM kb_alias WHERE alias = ?", (domain,)
        ).fetchone()
        if alias_row is not None:
            info = self._query_domain(alias_row[0])
            if info is not None:
                return info

        # Step 3: registrable domain fallback
        registrable = _registrable(domain)
        if registrable != domain:
            info = self._query_domain(registrable)
            if info is not None:
                return info

        # Step 4: unrecognized
        return self._unknown(domain)

    # ── Internals ───────────────────────────────────────────────────

    def _query_domain(self, domain: str) -> Optional[DomainInfo]:
        """Query kb_domain table for exact domain match."""
        if self._conn is None:
            return None
        row = self._conn.execute(
            """SELECT domain, owner, category, purpose_plain,
                      privacy_note, suggestion, confidence
               FROM kb_domain WHERE domain = ?""",
            (domain,),
        ).fetchone()
        if row is None:
            return None
        category = row[2] or "unrecognized"
        return DomainInfo(
            domain=row[0],
            owner=row[1],
            category=category,
            category_human=_HUMAN_CATEGORY.get(category, category),
            purpose_plain=row[3],
            privacy_note=row[4],
            suggestion=row[5],
            confidence=row[6] or "low",
            kb_hit=True,
        )

    @staticmethod
    def _unknown(domain: str) -> DomainInfo:
        return DomainInfo(
            domain=domain,
            owner=None,
            category="unrecognized",
            category_human="unrecognized service",
            purpose_plain=None,
            privacy_note=None,
            suggestion=None,
            confidence="low",
            kb_hit=False,
        )



