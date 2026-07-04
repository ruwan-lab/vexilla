"""FastAPI application factory — full dashboard with all screens."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from vexilla import __version__
from vexilla.config import Settings
from vexilla.store import Database

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"


def _mb(b: int) -> float:
    return round(b / 1048576, 1)


def _human_time(epoch: int) -> str:
    return time.strftime("%I:%M %p", time.gmtime(epoch)).lstrip("0")


def _human_date(epoch: int) -> str:
    return time.strftime("%b %d", time.gmtime(epoch))


def _today_start() -> int:
    now = time.time()
    return int(now - now % 86400)


def _week_start() -> int:
    return _today_start() - 6 * 86400


def _flag_icon(severity: str) -> str:
    return {"warning": "⚠", "notice": "⚑", "info": "ℹ"}.get(severity, "•")


def create_app() -> FastAPI:
    settings = Settings.load()
    settings.ensure_dirs()

    db = Database(settings.db_path)
    db.initialize()

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    app = FastAPI(
        title="Vexilla",
        version=__version__,
        description="Network transparency dashboard — local only.",
    )

    app.state.settings = settings
    app.state.db = db

    # ── Middleware ─────────────────────────────────────────────────
    @app.middleware("http")
    async def consent_check(request: Request, call_next):
        if not _consent_required(request):
            return await call_next(request)
        public_paths = {"/consent", "/api/consent", "/static", "/favicon.ico"}
        path = request.url.path
        if any(path.startswith(p) for p in public_paths):
            return await call_next(request)
        acknowledged = db.get_setting("consent_acknowledged")
        if acknowledged == "true":
            return await call_next(request)
        return RedirectResponse(url="/consent")

    # ── Shared template context ────────────────────────────────────
    def _context(request: Request, **extra) -> dict:
        data = {
            "request": request,
            "version": __version__,
            "flag_count": db.get_flag_count(),
        }
        data.update(extra)
        return data

    # ═══════════════════════════════════════════════════════════════
    # Screen 1 — Today / Dashboard
    # ═══════════════════════════════════════════════════════════════
    @app.get("/", response_class=HTMLResponse)
    async def dashboard_page(request: Request):
        today = _today_start()
        week = _week_start()

        # Summary from agg_hourly
        row = db.execute(
            """SELECT COUNT(DISTINCT app_id), COUNT(DISTINCT endpoint_id),
                      COALESCE(SUM(bytes_sent + bytes_recv), 0),
                      COALESCE(SUM(bg_bytes), 0)
               FROM agg_hourly WHERE hour_start >= ?""",
            (today,),
        ).fetchone()
        app_count = row[0] or 0
        domain_count = row[1] or 0
        total_bytes = row[2] or 0
        bg_bytes = row[3] or 0

        # Summary text from cache
        summary_row = db.execute(
            "SELECT text FROM summary WHERE day_start = ?", (today,)
        ).fetchone()
        summary_text = summary_row[0] if summary_row else None

        # Top apps today
        top_apps = db.get_top_apps(limit=5, since=today)

        # Top domains today
        top_domains = db.get_top_domains(limit=8, since=today)

        # Recent insights
        insights = db.execute(
            """SELECT id, kind, severity, title, body, suggestion, created_at
               FROM insight WHERE dismissed = 0 ORDER BY created_at DESC LIMIT 5"""
        ).fetchall()

        # Hourly breakdown (for the mini timeline) — today's hours
        hourly_rows = db.execute(
            """SELECT hour_start, SUM(bytes_sent + bytes_recv), SUM(bg_bytes)
               FROM agg_hourly WHERE hour_start >= ? GROUP BY hour_start ORDER BY hour_start""",
            (today,),
        ).fetchall()
        max_hourly = max(((r[1] or 0) for r in hourly_rows), default=0) or 1
        hours = []
        for r in hourly_rows:
            h = time.gmtime(r[0]).tm_hour
            hours.append({"hour": h, "total": r[1] or 0, "bg": r[2] or 0,
                          "pct": (r[1] or 0) / max_hourly * 100})

        return templates.TemplateResponse(
            request, "dashboard.html",
            _context(request,
                empty=(app_count == 0),
                summary_text=summary_text,
                app_count=app_count,
                domain_count=domain_count,
                total_mb=_mb(total_bytes),
                bg_mb=_mb(bg_bytes),
                top_apps=top_apps,
                top_domains=top_domains,
                insights=insights,
                hours=hours,
                flag_icon=_flag_icon,
                _mb=_mb,
            ),
        )

    # ═══════════════════════════════════════════════════════════════
    # Screen 2 — Apps
    # ═══════════════════════════════════════════════════════════════
    @app.get("/apps", response_class=HTMLResponse)
    async def apps_page(request: Request, days: int = 1, offset: int = 0, limit: int = 50):
        since = _today_start() if days == 1 else _today_start() - (days - 1) * 86400
        top_apps = db.get_top_apps(limit=limit, since=since)[offset:offset + limit]
        total = db.execute(
            "SELECT COUNT(DISTINCT app_id) FROM agg_hourly WHERE hour_start >= ?",
            (since,),
        ).fetchone()[0] or 0
        return templates.TemplateResponse(
            request, "apps.html",
            _context(request, apps=top_apps, days=days, offset=offset,
                     limit=limit, total=total, _mb=_mb),
        )

    @app.get("/apps/{app_id}", response_class=HTMLResponse)
    async def app_detail_page(request: Request, app_id: int):
        app_row = db.execute(
            "SELECT id, name, exe_path FROM app WHERE id = ?", (app_id,)
        ).fetchone()
        if not app_row:
            return templates.TemplateResponse(request, "dashboard.html",
                                              _context(request, empty=True))

        today = _today_start()
        # Total & bg for this app today
        agg = db.execute(
            """SELECT COALESCE(SUM(bytes_sent + bytes_recv), 0),
                      COALESCE(SUM(bg_bytes), 0),
                      COUNT(DISTINCT endpoint_id)
               FROM agg_hourly WHERE app_id = ? AND hour_start >= ?""",
            (app_id, today),
        ).fetchone()
        total_bytes = agg[0] or 0
        bg_bytes = agg[1] or 0
        services = agg[2] or 0

        # Endpoints for this app
        eps = db.execute(
            """SELECT e.id, e.ip, e.domain, e.name_source,
                      SUM(ag.bytes_sent + ag.bytes_recv)
               FROM agg_hourly ag JOIN endpoint e ON ag.endpoint_id = e.id
               WHERE ag.app_id = ? AND ag.hour_start >= ?
               GROUP BY e.id ORDER BY 5 DESC LIMIT 20""",
            (app_id, today),
        ).fetchall()

        # Hourly sparkline data
        hours = db.execute(
            """SELECT hour_start, SUM(bytes_sent + bytes_recv),
                      SUM(bg_bytes)
               FROM agg_hourly WHERE app_id = ? AND hour_start >= ?
               GROUP BY hour_start ORDER BY hour_start""",
            (app_id, today),
        ).fetchall()
        max_h = max(((r[1] or 0) for r in hours), default=0) or 1
        spark = [{"h": time.gmtime(r[0]).tm_hour, "pct": (r[1] or 0) / max_h * 100} for r in hours]

            # Insights for this app
        ins = db.execute(
            """SELECT id, kind, severity, title, body, created_at
               FROM insight WHERE app_id = ? AND dismissed = 0
               ORDER BY created_at DESC LIMIT 10""",
            (app_id,),
        ).fetchall()

        return templates.TemplateResponse(
            request, "app_detail.html",
            _context(request,
                app={"id": app_row[0], "name": app_row[1], "exe_path": app_row[2]},
                total_mb=_mb(total_bytes),
                bg_mb=_mb(bg_bytes), services=services,
                endpoints=eps, spark=spark, insights=ins,
                flag_icon=_flag_icon, _mb=_mb,
            ),
        )

    # ═══════════════════════════════════════════════════════════════
    # Screen 3 — Services (domains)
    # ═══════════════════════════════════════════════════════════════
    @app.get("/services", response_class=HTMLResponse)
    async def services_page(request: Request, days: int = 1, offset: int = 0, limit: int = 50):
        since = _today_start() if days == 1 else _today_start() - (days - 1) * 86400
        top = db.get_top_domains(limit=limit, since=since)[offset:offset + limit]
        total = db.execute(
            "SELECT COUNT(DISTINCT endpoint_id) FROM agg_hourly WHERE hour_start >= ?",
            (since,),
        ).fetchone()[0] or 0
        return templates.TemplateResponse(
            request, "services.html",
            _context(request, domains=top, days=days, offset=offset,
                     limit=limit, total=total, _mb=_mb),
        )

    @app.get("/services/{endpoint_id}", response_class=HTMLResponse)
    async def service_detail_page(request: Request, endpoint_id: int):
        ep_row = db.execute(
            "SELECT id, ip, domain, name_source FROM endpoint WHERE id = ?",
            (endpoint_id,),
        ).fetchone()
        if not ep_row:
            return RedirectResponse(url="/services")

        today = _today_start()
        agg = db.execute(
            """SELECT COALESCE(SUM(bytes_sent + bytes_recv), 0),
                      COALESCE(SUM(conn_count), 0)
               FROM agg_hourly WHERE endpoint_id = ? AND hour_start >= ?""",
            (endpoint_id, today),
        ).fetchone()
        total_bytes = agg[0] or 0
        conn_count = agg[1] or 0

        # Apps hitting this endpoint
        apps_on = db.execute(
            """SELECT a.id, a.name, SUM(ag.bytes_sent + ag.bytes_recv)
               FROM agg_hourly ag JOIN app a ON ag.app_id = a.id
               WHERE ag.endpoint_id = ? AND ag.hour_start >= ?
               GROUP BY a.id ORDER BY 3 DESC""",
            (endpoint_id, today),
        ).fetchall()

        # Insights for this endpoint
        ins = db.execute(
            """SELECT id, kind, severity, title, body, created_at
               FROM insight WHERE endpoint_id = ? AND dismissed = 0
               ORDER BY created_at DESC LIMIT 5""",
            (endpoint_id,),
        ).fetchall()

        return templates.TemplateResponse(
            request, "service_detail.html",
            _context(request,
                ep={"id": ep_row[0], "ip": ep_row[1], "domain": ep_row[2],
                     "name_source": ep_row[3]},
                total_mb=_mb(total_bytes),
                conn_count=conn_count,
                apps_on=apps_on,
                insights=ins,
                flag_icon=_flag_icon, _mb=_mb,
            ),
        )

    # ═══════════════════════════════════════════════════════════════
    # Screen 4 — Timeline
    # ═══════════════════════════════════════════════════════════════
    @app.get("/timeline", response_class=HTMLResponse)
    async def timeline_page(request: Request, days: int = 1):
        since = _today_start() if days == 1 else _today_start() - (days - 1) * 86400

        hours = db.execute(
            """SELECT hour_start, SUM(bytes_sent + bytes_recv), SUM(bg_bytes)
               FROM agg_hourly WHERE hour_start >= ?
               GROUP BY hour_start ORDER BY hour_start""",
            (since,),
        ).fetchall()

        max_h = max(((r[1] or 0) for r in hours), default=0) or 1
        timeline = []
        for r in hours:
            h = time.gmtime(r[0])
            timeline.append({
                "hour": f"{h.tm_mon}/{h.tm_mday} {h.tm_hour}:00",
                "total_pct": (r[1] or 0) / max_h * 100,
                "bg_pct": (r[2] or 0) / max_h * 100 if r[2] else 0,
                "total_mb": _mb(r[1] or 0),
                "bg_mb": _mb(r[2] or 0),
            })

        # Notable moments = insights on the timeline
        notable = db.execute(
            """SELECT kind, severity, title, created_at
               FROM insight WHERE dismissed = 0 AND created_at >= ?
               ORDER BY created_at DESC LIMIT 20""",
            (since,),
        ).fetchall()

        return templates.TemplateResponse(
            request, "timeline.html",
            _context(request, timeline=timeline, notable=notable,
                     days=days, flag_icon=_flag_icon),
        )

    # ═══════════════════════════════════════════════════════════════
    # Screen 5 — Flags (insights)
    # ═══════════════════════════════════════════════════════════════
    @app.get("/flags", response_class=HTMLResponse)
    async def flags_page(request: Request, kind: str = ""):
        if kind:
            rows = db.execute(
                """SELECT id, kind, severity, title, body, suggestion,
                          evidence, created_at
                   FROM insight WHERE dismissed = 0 AND kind = ?
                   ORDER BY created_at DESC LIMIT 100""",
                (kind,),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT id, kind, severity, title, body, suggestion,
                          evidence, created_at
                   FROM insight WHERE dismissed = 0
                   ORDER BY created_at DESC LIMIT 100"""
            ).fetchall()

        kinds = db.execute(
            "SELECT DISTINCT kind FROM insight ORDER BY kind"
        ).fetchall()

        return templates.TemplateResponse(
            request, "flags.html",
            _context(request, flags=rows, kinds=[r[0] for r in kinds],
                     filter_kind=kind, flag_icon=_flag_icon),
        )

    @app.post("/api/flags/{flag_id}/dismiss")
    async def dismiss_flag(request: Request, flag_id: int):
        db.execute("UPDATE insight SET dismissed = 1 WHERE id = ?", (flag_id,))
        db._get_conn().commit()
        return RedirectResponse(url="/flags", status_code=303)

    @app.post("/api/flags/dismiss-all")
    async def dismiss_all_flags(request: Request):
        db.execute("UPDATE insight SET dismissed = 1 WHERE dismissed = 0")
        db._get_conn().commit()
        return RedirectResponse(url="/flags", status_code=303)

    @app.get("/api/flags/count")
    async def flag_count_json(request: Request):
        return {"count": db.get_flag_count()}

    # ═══════════════════════════════════════════════════════════════
    # Screen 6 — Settings
    # ═══════════════════════════════════════════════════════════════
    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        retention = db.get_setting("retention_days", "30")
        return templates.TemplateResponse(
            request, "settings.html",
            _context(request,
                retention_days=int(retention),
                db_size=_mb(db.path.stat().st_size) if db.path.exists() else 0,
                capture="Poll-based (/proc + conntrack)",
                dns="AF_PACKET (requires CAP_NET_RAW)" if True else "unavailable",
            ),
        )

    @app.post("/api/settings")
    async def update_settings(request: Request, retention_days: int = Form(30)):
        db.set_setting("retention_days", str(retention_days))
        return RedirectResponse(url="/settings", status_code=303)

    # ═══════════════════════════════════════════════════════════════
    # Data export & reset
    # ═══════════════════════════════════════════════════════════════
    @app.get("/api/data/export")
    async def export_data(request: Request):
        """Export all runtime data as downloadable JSON."""
        now = int(time.time())
        data = {
            "exported_at": now,
            "vexilla_version": __version__,
            "apps": [dict(r) for r in db.execute(
                "SELECT id, name, exe_path, first_seen, last_seen FROM app"
            ).fetchall()],
            "endpoints": [dict(r) for r in db.execute(
                "SELECT id, ip, domain, name_source, first_seen, last_seen FROM endpoint"
            ).fetchall()],
            "flows": [dict(r) for r in db.execute(
                """SELECT id, app_id, endpoint_id, protocol, remote_port,
                          bytes_sent, bytes_recv, is_background, started_at, last_seen
                   FROM flow ORDER BY last_seen DESC LIMIT 10000"""
            ).fetchall()],
            "dns_cache": [dict(r) for r in db.execute(
                "SELECT id, ip, domain, observed_at, ttl FROM dns_cache"
            ).fetchall()],
            "agg_hourly": [dict(r) for r in db.execute(
                """SELECT id, hour_start, app_id, endpoint_id,
                          bytes_sent, bytes_recv, conn_count, bg_bytes
                   FROM agg_hourly ORDER BY hour_start DESC"""
            ).fetchall()],
            "insights": [dict(r) for r in db.execute(
                """SELECT id, kind, severity, app_id, endpoint_id, title,
                          body, suggestion, evidence, created_at, dismissed
                   FROM insight ORDER BY created_at DESC"""
            ).fetchall()],
            "summary": [dict(r) for r in db.execute(
                "SELECT id, day_start, text, stats_json, generated_at FROM summary"
            ).fetchall()],
        }
        json_bytes = json.dumps(data, indent=2, default=str).encode()
        return Response(
            content=json_bytes,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="vexilla-export-{now}.json"',
            },
        )

    @app.get("/api/data/export/csv")
    async def export_data_csv(request: Request):
        """Export flows data as downloadable CSV."""
        now = int(time.time())
        import csv, io

        rows = db.execute(
            """SELECT a.name as app, e.ip, e.domain, f.protocol,
                      f.remote_port, f.bytes_sent, f.bytes_recv,
                      f.is_background, f.started_at, f.last_seen
               FROM flow f
               JOIN app a ON f.app_id = a.id
               JOIN endpoint e ON f.endpoint_id = e.id
               ORDER BY f.last_seen DESC LIMIT 50000"""
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["app", "ip", "domain", "protocol", "port",
                         "bytes_sent", "bytes_recv", "is_background",
                         "started_at", "last_seen"])
        for r in rows:
            writer.writerow(list(r))

        csv_bytes = output.getvalue().encode()
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="vexilla-flows-{now}.csv"',
            },
        )

    @app.get("/api/data/export/csv/insights")
    async def export_insights_csv(request: Request):
        """Export insights data as downloadable CSV."""
        now = int(time.time())
        import csv, io

        rows = db.execute(
            """SELECT i.kind, i.severity, a.name as app, e.ip, e.domain,
                      i.title, i.body, i.suggestion, i.created_at, i.dismissed
               FROM insight i
               LEFT JOIN app a ON i.app_id = a.id
               LEFT JOIN endpoint e ON i.endpoint_id = e.id
               ORDER BY i.created_at DESC LIMIT 5000"""
        ).fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["kind", "severity", "app", "ip", "domain",
                         "title", "body", "suggestion", "created_at", "dismissed"])
        for r in rows:
            writer.writerow(list(r))

        csv_bytes = output.getvalue().encode()
        return Response(
            content=csv_bytes,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="vexilla-insights-{now}.csv"',
            },
        )

    @app.post("/api/data/reset")
    async def reset_data(request: Request):
        """Delete all runtime data but keep consent and settings."""
        db.execute("DELETE FROM flow")
        db.execute("DELETE FROM agg_hourly")
        db.execute("DELETE FROM endpoint")
        db.execute("DELETE FROM app")
        db.execute("DELETE FROM dns_cache")
        db.execute("DELETE FROM insight")
        db.execute("DELETE FROM summary")
        db._get_conn().commit()
        logger.warning("All runtime data cleared via Settings")
        return RedirectResponse(url="/settings", status_code=303)

    # ── Static routes ─────────────────────────────────────────────
    @app.get("/favicon.ico", response_class=Response)
    async def favicon(request: Request):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#4a90d9"/><text x="16" y="23" font-size="20" text-anchor="middle" fill="white" font-family="sans-serif">V</text></svg>'
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/consent", response_class=HTMLResponse)
    async def consent_page(request: Request):
        already = db.get_setting("consent_acknowledged") == "true"
        return templates.TemplateResponse(
            request, "consent.html",
            {"version": __version__, "already": already},
        )

    @app.post("/api/consent")
    async def accept_consent(request: Request):
        db.set_setting("consent_acknowledged", "true")
        logger.info("Consent acknowledged")
        return RedirectResponse(url="/", status_code=303)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__, "db_healthy": db.is_healthy()}

    return app


def _consent_required(request: Request) -> bool:
    return request.app.state.settings.consent_required
