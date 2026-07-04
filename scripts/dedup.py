"""Deduplicate existing app and endpoint records.

Run this AFTER updating the schema with UNIQUE indexes.
Merges duplicate endpoints by IP, reassigns their flows,
then removes the duplicates.
"""
import sys
sys.path.insert(0, "/usr/lib/vexilla/vendor")
sys.path.insert(0, "/usr/lib/vexilla/src")
import os
os.environ["VEXILLA_DB_PATH"] = "/var/lib/vexilla/vexilla.db"

from vexilla.store.database import Database
from vexilla.config import Settings
import sqlite3

settings = Settings.load()
print(f"DB: {settings.db_path}")

# Connect directly to handle dedup
conn = sqlite3.connect(str(settings.db_path))

# 1. Dedup endpoints: keep the first endpoint for each IP
print("\n=== Deduplicating endpoints ===")
dups = conn.execute("""
    SELECT e.ip, COUNT(*), MIN(e.id) as keep_id
    FROM endpoint e
    GROUP BY e.ip
    HAVING COUNT(*) > 1
""").fetchall()
print(f"Found {len(dups)} IPs with duplicate endpoints")

for ip, count, keep_id in dups:
    dup_ids = conn.execute(
        "SELECT id FROM endpoint WHERE ip = ? AND id != ?",
        (ip, keep_id)
    ).fetchall()
    ids = [r[0] for r in dup_ids]
    
    # Reassign flows to the kept endpoint
    conn.execute(
        f"UPDATE flow SET endpoint_id = ? WHERE endpoint_id IN ({','.join('?' for _ in ids)})",
        (keep_id, *ids)
    )
    # Remove duplicates
    conn.execute(
        f"DELETE FROM endpoint WHERE id IN ({','.join('?' for _ in ids)})",
        ids
    )
    print(f"  {ip}: merged {len(ids)} dupes into id {keep_id}")

# 2. Dedup apps: keep the first app for each name
print("\n=== Deduplicating apps ===")
dups = conn.execute("""
    SELECT a.name, COUNT(*), MIN(a.id) as keep_id
    FROM app a
    GROUP BY a.name
    HAVING COUNT(*) > 1
""").fetchall()
print(f"Found {len(dups)} names with duplicate apps")

for name, count, keep_id in dups:
    dup_ids = conn.execute(
        "SELECT id FROM app WHERE name = ? AND id != ?",
        (name, keep_id)
    ).fetchall()
    ids = [r[0] for r in dup_ids]
    
    # Reassign flows
    conn.execute(
        f"UPDATE flow SET app_id = ? WHERE app_id IN ({','.join('?' for _ in ids)})",
        (keep_id, *ids)
    )
    # Reassign agg_hourly
    conn.execute(
        f"UPDATE agg_hourly SET app_id = ? WHERE app_id IN ({','.join('?' for _ in ids)})",
        (keep_id, *ids)
    )
    # Remove duplicates
    conn.execute(
        f"DELETE FROM app WHERE id IN ({','.join('?' for _ in ids)})",
        ids
    )
    print(f"  {name}: merged {len(ids)} dupes into id {keep_id}")

conn.commit()

# 3. Create the UNIQUE indexes (if not already created)
print("\n=== Creating UNIQUE indexes ===")
conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_app_name ON app(name)")
conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_endpoint_ip ON endpoint(ip)")
conn.commit()

# 4. Verify
print("\n=== Verification ===")
apps = conn.execute("SELECT COUNT(*) FROM app").fetchone()[0]
endpoints = conn.execute("SELECT COUNT(*) FROM endpoint").fetchone()[0]
flows = conn.execute("SELECT COUNT(*) FROM flow").fetchone()[0]
print(f"Apps: {apps}, Endpoints: {endpoints}, Flows: {flows}")

conn.close()
print("\nDone!")
