"""Vexilla CLI — Typer application.

Commands: status, serve, reset, today, apps, domains (today/apps/domains stubs).
"""

from __future__ import annotations

import logging
import sys

import typer

from vexilla import __version__
from vexilla.config import Settings, _config_path
from vexilla.store import Database

app = typer.Typer(
    name="vexilla",
    help="See what your device is really talking to — in plain English.",
    no_args_is_help=True,
)

_log_configured = False


def _setup_logging(level: str = "INFO") -> None:
    global _log_configured
    if not _log_configured:
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format="%(levelname)s  %(name)s  %(message)s",
            stream=sys.stderr,
        )
        _log_configured = True


def _get_db(settings: Settings) -> Database:
    db = Database(settings.db_path)
    db.initialize()
    return db


# ═══════════════════════════════════════════════════════════════════
# Callbacks
# ═══════════════════════════════════════════════════════════════════


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Vexilla — network transparency for normal people."""
    if version:
        print(f"vexilla {__version__}")
        raise typer.Exit()

    level = "DEBUG" if verbose else "INFO"
    _setup_logging(level)

    # Load settings once and store in context
    if not hasattr(ctx, "obj") or ctx.obj is None:
        settings = Settings.load()
        settings.ensure_dirs()
        ctx.obj = settings


# ═══════════════════════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════════════════════


@app.command()
def status(
    ctx: typer.Context,
) -> None:
    """Show daemon and database health."""
    settings: Settings = ctx.obj
    db_path = settings.db_path
    db = _get_db(settings)

    healthy = db.is_healthy()
    db_size = "N/A"
    if db_path.exists():
        db_size = _human_size(db_path.stat().st_size)

    print(f"Vexilla {__version__}")
    print(f"  Database:    {db_path}  ({db_size})")
    print(f"  Config:      {_config_path()}")
    print(f"  Dashboard:   http://{settings.host}:{settings.port}")
    print(f"  Retention:   {settings.retention_days} days")
    print(f"  Capture:     {_capture_method()}")
    print(f"  DB healthy:  {'yes' if healthy else 'NO'}")
    print()

    if healthy:
        print("✓ Vexilla is ready.")
        raise typer.Exit(0)
    else:
        print("✗ Database is not healthy. Try `vexilla reset` and restart.")
        raise typer.Exit(1)


@app.command()
def serve(
    ctx: typer.Context,
    host: str | None = typer.Option(None, "--host", help="Override bind host."),
    port: int | None = typer.Option(None, "--port", "-p", help="Override bind port."),
) -> None:
    """Start the web dashboard server."""
    settings: Settings = ctx.obj
    host = host or settings.host
    port = port or settings.port

    # Ensure DB is ready before serving
    db = _get_db(settings)

    # Start the collector daemon in the background
    from vexilla.collector.daemon import CollectorDaemon

    collector = CollectorDaemon(db, poll_interval=settings.poll_interval_s)
    collector.start()

    # Start the insight engine scheduler
    from vexilla.insight.scheduler import InsightScheduler

    insight_scheduler = InsightScheduler(
        db,
        kb_path=str(settings.kb_path) if settings.kb_path.exists() else None,
        insight_interval=settings.insight_interval_s,
    )
    insight_scheduler.start()

    print(f"Starting Vexilla dashboard on http://{host}:{port}")
    print("  Collector:  active (poll every {:.1f}s)".format(settings.poll_interval_s))
    print("  Insight:    active (every {:.0f}s)".format(settings.insight_interval_s))
    print("Press Ctrl+C to stop.")

    # Lazy import so uvicorn isn't loaded for simple commands
    import uvicorn

    try:
        uvicorn.run(
            "vexilla.api.app:create_app",
            host=host,
            port=port,
            factory=True,
            log_level=settings.log_level.lower(),
            reload=False,
        )
    finally:
        insight_scheduler.stop(timeout=3.0)
        collector.stop(timeout=3.0)


@app.command()
def reset(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation."),
) -> None:
    """Delete all collected data (runtime database)."""
    settings: Settings = ctx.obj
    db_path = settings.db_path

    if not db_path.exists():
        print("No data to reset.")
        raise typer.Exit(0)

    if not force:
        typer.confirm(
            f"Delete all network activity data at {db_path}?", abort=True
        )

    db_path.unlink()
    print(f"Deleted {db_path}")
    print("Data reset. Restart the service to start fresh.")


# ═══════════════════════════════════════════════════════════════════
# Query commands (wired to agg_hourly aggregates)
# ═══════════════════════════════════════════════════════════════════


@app.command()
def prune(
    ctx: typer.Context,
) -> None:
    """Manually prune old data (runs the retention job)."""
    settings: Settings = ctx.obj
    db = _get_db(settings)
    result = db.prune(settings.retention_days)
    deleted = sum(result.values())
    if deleted:
        print(f"Pruned {deleted} rows: {result}")
    else:
        print("Nothing to prune — all data is within the retention window.")


@app.command()
def today(
    ctx: typer.Context,
) -> None:
    """Show today's plain-language summary with insight engine output."""
    settings: Settings = ctx.obj
    db = _get_db(settings)

    # Try to read the cached summary from the insight engine
    today_start = int(__import__("time").time())
    today_start = int(today_start - today_start % 86400)
    row = db.execute(
        "SELECT text FROM summary WHERE day_start = ?", (today_start,)
    ).fetchone()

    if row is None:
        # Fall back to raw aggregates
        summary = db.get_today_summary()
        total = _human_size(summary["total_bytes"])
        bg = _human_size(summary["bg_bytes"])
        print(f"📊  Today's summary (no insight engine yet)")
        print(f"     {summary['app_count']} apps  ·  {summary['domain_count']} services")
        print(f"     {total} total  ·  {bg} in background")
    else:
        print(f"📊  Today's summary")
        print()
        print(f"     {row[0]}")

        # Show flags
        flag_count = db.get_flag_count()
        if flag_count > 0:
            print()
            print(f"  Flags: {flag_count} item(s) — run 'vexilla flags' or open dashboard")

    # Show recent insights
    insights = db.execute(
        """SELECT kind, severity, title, created_at FROM insight
           WHERE created_at >= ? ORDER BY created_at DESC LIMIT 5""",
        (today_start,),
    ).fetchall()

    if insights:
        print()
        for ins in insights:
            icon = {"warning": "⚠", "notice": "⚑", "info": "ℹ"}.get(ins[1], "•")
            print(f"     {icon} {ins[2]}")


@app.command()
def apps(
    ctx: typer.Context,
    limit: int = typer.Option(10, "--limit", "-n", help="Number of apps to show."),
    days: int = typer.Option(1, "--days", "-d", help="Look back N days."),
) -> None:
    """Show top apps by data usage."""
    settings: Settings = ctx.obj
    db = _get_db(settings)
    since = int(__import__("time").time()) - days * 86400

    top = db.get_top_apps(limit=limit, since=since)
    if not top:
        print("No data yet. Start `vexilla serve` and wait for the collector.")
        raise typer.Exit(0)

    print(f"{'App':<24} {'Total':>10} {'BG':>10}  {'%BG':>5}  {'Services':>8}")
    print("-" * 62)
    for app in top:
        total = _human_size(app["total_bytes"])
        bg = _human_size(app["bg_bytes"])
        bg_pct = (
            round(app["bg_bytes"] / app["total_bytes"] * 100)
            if app["total_bytes"]
            else 0
        )
        name = app["name"][:23]
        print(
            f"{name:<24} {total:>10} {bg:>10}  {bg_pct:>4}%  {app['service_count']:>8}"
        )


@app.command()
def domains(
    ctx: typer.Context,
    limit: int = typer.Option(10, "--limit", "-n", help="Number of domains to show."),
    days: int = typer.Option(1, "--days", "-d", help="Look back N days."),
) -> None:
    """Show top domains / services contacted."""
    settings: Settings = ctx.obj
    db = _get_db(settings)
    since = int(__import__("time").time()) - days * 86400

    top = db.get_top_domains(limit=limit, since=since)
    if not top:
        print("No data yet. Start `vexilla serve` and wait for the collector.")
        raise typer.Exit(0)

    print(f"{'Domain / IP':<40} {'Total':>10}  {'Conns':>6}  {'Apps':>5}")
    print("-" * 65)
    for ep in top:
        label = ep["domain"] or ep["ip"] or "(unknown)"
        total = _human_size(ep["total_bytes"])
        print(
            f"{label:<40} {total:>10}  {ep['conn_count']:>6}  {ep['app_count']:>5}"
        )


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _capture_method() -> str:
    """Return a human-readable string describing the active capture path."""
    try:
        from vexilla.collector.ebpf import is_bcc_available

        available, msg = is_bcc_available()
        if available:
            return f"eBPF ({msg})"
        return f"Poll-based (/proc + conntrack)  [{msg}]"
    except Exception:
        return "Poll-based (/proc + conntrack)"


def _human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} TB"
