"""Knowledge base build pipeline — creates kb.db from seed data.

Run offline by maintainers:
    python -m vexilla.kb.build.pipeline

Produces data/kb.db for bundling with the app.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

from vexilla.kb.build.seed_data import ALL_SEEDS, ALIASES

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS kb_domain (
    domain         TEXT PRIMARY KEY,
    owner          TEXT,
    category       TEXT NOT NULL,
    purpose_plain  TEXT NOT NULL,
    privacy_note   TEXT,
    suggestion     TEXT,
    confidence     TEXT NOT NULL,
    source         TEXT NOT NULL,
    updated_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kb_category ON kb_domain(category);

CREATE TABLE IF NOT EXISTS kb_alias (
    alias   TEXT PRIMARY KEY,
    domain  TEXT NOT NULL REFERENCES kb_domain(domain)
);

CREATE TABLE IF NOT EXISTS kb_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def build_kb(
    output_path: str | Path = "data/kb.db",
    source: str = "curated",
    extra_domains: Optional[list[tuple]] = None,
    extra_aliases: Optional[dict[str, str]] = None,
) -> Path:
    """Build the kb.db database from seed domain data.

    Args:
        output_path: Path to write the output kb.db file.
        source: Source label for all entries ('curated', 'list', or 'llm').

    Returns:
        Path to the created kb.db file.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing file to start fresh
    if output.exists():
        output.unlink()

    conn = sqlite3.connect(str(output))
    conn.executescript(SCHEMA_SQL)

    now = int(time.time())

    # ── Insert domains ─────────────────────────────────────────────

    count = 0
    for entry in ALL_SEEDS:
        domain = entry[0]
        owner = entry[1]
        category = entry[2]
        purpose = entry[3]
        privacy = entry[4] if len(entry) > 4 else None
        suggestion = entry[5] if len(entry) > 5 else None
        confidence = entry[6] if len(entry) > 6 else "medium"

        conn.execute(
            """INSERT OR IGNORE INTO kb_domain
               (domain, owner, category, purpose_plain, privacy_note,
                suggestion, confidence, source, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (domain, owner, category, purpose, privacy,
             suggestion, confidence, source, now),
        )
        count += 1

    # ── Insert aliases ─────────────────────────────────────────────

    alias_count = 0
    for alias, domain in ALIASES.items():
        # Only insert if the parent domain exists
        existing = conn.execute(
            "SELECT 1 FROM kb_domain WHERE domain = ?", (domain,)
        ).fetchone()
        if existing:
            conn.execute(
                "INSERT OR IGNORE INTO kb_alias (alias, domain) VALUES (?, ?)",
                (alias, domain),
            )
            alias_count += 1

    # ── Merge extra domains from list imports ───────────────────────
    if extra_domains:
        for entry in extra_domains:
            domain = entry[0] if len(entry) > 0 else ""
            owner = entry[1] if len(entry) > 1 else None
            category = entry[2] if len(entry) > 2 else "unrecognized"
            purpose = entry[3] if len(entry) > 3 else None
            privacy = entry[4] if len(entry) > 4 else None
            suggestion = entry[5] if len(entry) > 5 else None
            confidence = entry[6] if len(entry) > 6 else "medium"
            if domain:
                conn.execute(
                    """INSERT OR IGNORE INTO kb_domain
                       (domain, owner, category, purpose_plain, privacy_note,
                        suggestion, confidence, source, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'list', ?)""",
                    (domain, owner, category, purpose, privacy,
                     suggestion, confidence, now),
                )
                count += 1

    if extra_aliases:
        for alias, domain in extra_aliases.items():
            existing = conn.execute(
                "SELECT 1 FROM kb_domain WHERE domain = ?", (domain,)
            ).fetchone()
            if existing:
                conn.execute(
                    "INSERT OR IGNORE INTO kb_alias (alias, domain) VALUES (?, ?)",
                    (alias, domain),
                )
                alias_count += 1

    # ── Metadata ───────────────────────────────────────────────────

    conn.execute(
        "INSERT OR REPLACE INTO kb_meta (key, value) VALUES ('version', '1')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO kb_meta (key, value) VALUES ('build_date', ?)",
        (str(int(time.time())),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO kb_meta (key, value) VALUES ('entry_count', ?)",
        (str(count),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO kb_meta (key, value) VALUES ('alias_count', ?)",
        (str(alias_count),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO kb_meta (key, value) VALUES ('source', ?)",
        (source,),
    )
    conn.execute(
        "INSERT OR REPLACE INTO kb_meta (key, value) VALUES ('schema_version', '1')",
    )

    conn.commit()
    conn.close()

    size = output.stat().st_size
    logger.info(
        "KB built: %s (%d domains, %d aliases, %s)",
        output, count, alias_count, _human_size(size),
    )
    print(f"KB built: {output} ({count} domains, {alias_count} aliases, {_human_size(size)})")

    return output


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# ═══════════════════════════════════════════════════════════════════
# Direct execution entry point
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s  %(message)s",
    )
    build_kb()
