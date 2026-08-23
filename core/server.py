"""
FastAPI application factory.

Startup (lifespan):
  1. database schema - Alembic migrations on Postgres, create_all on SQLite
  2. demo seed data (optional)
  3. push the Vapi assistant configuration (optional, VAPI_SYNC_ON_STARTUP)

Routers:
  /patients                 REST API from the assessment spec (public)
  /api/v1/auth              dashboard login (JWT)
  /api/v1/calls             call transcripts + analysis (JWT)
  /api/v1/dashboard         stats + status (status is public: keep-alive target)
  /api/v1/voice             Vapi custom-LLM endpoint + webhook (shared secret)
  /api/v1/healthcheck, /api/v1/logs   health check + JSON log viewer
  /app                      Next.js dashboard (static export), when built; / redirects there
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from config import ROOT_DIR, get_settings
from core.logger.logger import LOG
from core.middlewares.middleware import middleware_handler
from core.responses import install_exception_handlers

STATIC_DIR = ROOT_DIR / "static"
UI_PREFIX = "/app"  # must match `basePath` in frontend/next.config.ts


def init_database() -> None:
    from core import database

    settings = get_settings()
    if settings.is_sqlite:
        database.create_all()
        LOG.info("db.ready", extra={"event": "db.ready", "engine": "sqlite"})
        return

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT_DIR / "alembic"))
    command.upgrade(cfg, "head")
    LOG.info("db.ready", extra={"event": "db.ready", "engine": "postgres", "migrations": "head"})


def seed_database() -> None:
    from core.database import engine
    from core.seed import seed_if_empty

    with Session(engine) as session:
        seed_if_empty(session)


async def sync_vapi_if_configured() -> None:
    settings = get_settings()
    if not (settings.vapi_sync_on_startup and settings.vapi_api_key and settings.base_url):
        return
    try:
        from modules.voice.vapi_setup import sync_assistant

        result = await sync_assistant()
        LOG.info("vapi.synced", extra={"event": "vapi.synced", **result})
    except Exception as exc:  # never block startup on a vendor hiccup
        LOG.error(f"vapi.sync_failed: {exc}", extra={"event": "vapi.sync_failed"})


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    LOG.info(
        "app.starting",
        extra={"event": "app.starting", "environment": settings.environment, "base_url": settings.base_url},
    )
    try:
        init_database()
        seed_database()
    except Exception as exc:
        # Surface loudly but keep the process alive so /healthcheck + logs stay reachable.
        LOG.exception(f"db.init_failed: {exc}", extra={"event": "db.init_failed"})
    await sync_vapi_if_configured()
    yield
    LOG.info("app.stopping", extra={"event": "app.stopping"})


def init_routers(app_: FastAPI) -> None:
    from modules.auth.auth_routes import API_ROUTER as AUTH_ROUTER
    from modules.calls.calls_routes import API_ROUTER as CALLS_ROUTER
    from modules.dashboard.dashboard_routes import API_ROUTER as DASHBOARD_ROUTER
    from modules.healthcheck.healthcheck_routes import API_ROUTER as HEALTH_ROUTER
    from modules.logviewer.log_viewer_routes import API_ROUTER as LOG_VIEWER_ROUTER
    from modules.patients.patients_routes import API_ROUTER as PATIENTS_API_ROUTER
    from modules.patients.patients_routes import ROOT_ROUTER as PATIENTS_ROOT_ROUTER
    from modules.voice.voice_routes import API_ROUTER as VOICE_ROUTER

    app_.include_router(PATIENTS_ROOT_ROUTER)
    app_.include_router(PATIENTS_API_ROUTER)
    app_.include_router(AUTH_ROUTER)
    app_.include_router(CALLS_ROUTER)
    app_.include_router(DASHBOARD_ROUTER)
    app_.include_router(VOICE_ROUTER)
    app_.include_router(HEALTH_ROUTER)
    app_.include_router(LOG_VIEWER_ROUTER)


def mount_frontend(app_: FastAPI) -> None:
    """Serve the Next.js static export (frontend/out -> static/) with clean URLs (/login -> login.html)."""
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return
    next_assets = STATIC_DIR / "_next"
    if next_assets.exists():
        app_.mount(f"{UI_PREFIX}/_next", StaticFiles(directory=next_assets), name="next-assets")
    not_found = STATIC_DIR / "404.html"
    static_root = STATIC_DIR.resolve()

    @app_.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url=UI_PREFIX, status_code=307)

    @app_.api_route(UI_PREFIX, methods=["GET", "HEAD"], include_in_schema=False)
    @app_.api_route(UI_PREFIX + "/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(full_path: str = "", request: Request = None):
        path = full_path.strip("/")
        candidates = (
            [STATIC_DIR / path, STATIC_DIR / f"{path}.html", STATIC_DIR / path / "index.html"] if path else [index]
        )
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file() and (resolved == static_root or static_root in resolved.parents):
                return FileResponse(resolved)
        if not_found.exists():
            return FileResponse(not_found, status_code=404)
        return FileResponse(index)


def make_middleware() -> list[Middleware]:
    return [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ]


def create_app() -> FastAPI:
    settings = get_settings()
    app_ = FastAPI(
        title="Patient Voice Agent API",
        description=settings.description,
        version=settings.version,
        middleware=make_middleware(),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    install_exception_handlers(app_)
    init_routers(app_=app_)
    middleware_handler(app=app_)
    mount_frontend(app_)
    return app_


app = create_app()
