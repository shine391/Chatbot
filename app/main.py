"""FastAPI application entry point."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.webhooks.facebook import router as facebook_router
from app.api.webhooks.instagram import router as instagram_router
from app.api.webhooks.shipping import router as shipping_router
from app.api.webhooks.tiktok import router as tiktok_router
from app.api.webhooks.website import router as website_router
from app.config import get_settings
from app.core.limiter import limiter
from app.core.live_chat import live_chat_manager
from app.database.session import close_db, get_engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    settings = get_settings()
    logger.info(f"Starting {settings.app_name} in {settings.app_env.value} mode")
    engine = get_engine()
    await init_db(engine)
    logger.info("Database initialized")

    # Start live chat Redis pub/sub sync
    await live_chat_manager.start_redis_sync(settings.redis_url)

    # Pre-warm AI Engine and Deduplicator singletons to eliminate cold-start request latency
    try:
        from app.core.conversation import get_shared_ai_engine, get_shared_deduplicator

        get_shared_ai_engine()
        get_shared_deduplicator()
        logger.info("Pre-warmed AI Engine and Deduplicator singletons")
    except Exception as exc:
        logger.warning(f"Could not pre-warm singletons: {exc}")

    # Pre-warm database connection pool
    try:
        from sqlalchemy import text

        async def _warmup_conn() -> None:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.gather(*[_warmup_conn() for _ in range(30)])
        logger.info("Pre-warmed database connection pool (30 connections)")
    except Exception as exc:
        logger.warning(f"Could not pre-warm DB pool: {exc}")

    yield

    await live_chat_manager.stop_redis_sync()
    await close_db(engine)
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    # Initialize Sentry APM if configured
    if settings.sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.types import Event, Hint

            def _filter_sentry_pii(event: Event, hint: Hint) -> Event | None:
                if "request" in event:
                    req = event["request"]
                    if isinstance(req, dict):
                        headers = req.get("headers")
                        if isinstance(headers, dict):
                            for h in ("authorization", "x-carrier-token", "cookie"):
                                if h in headers:
                                    headers[h] = "[FILTERED]"
                return event

            sentry_sdk.init(
                dsn=settings.sentry_dsn,
                traces_sample_rate=0.2,
                before_send=_filter_sentry_pii,
            )
            logger.info("Sentry APM initialized with PII masking.")
        except Exception as e:
            logger.warning(f"Failed to initialize Sentry APM: {e}")

    app = FastAPI(
        title=settings.app_name,
        description="AI Customer Service Agent - Đa kênh (Facebook, Instagram, TikTok, Website)",
        version="0.1.0",
        lifespan=lifespan,
    )

    # SlowAPI rate limiter state & error handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

    # CORS configuration
    raw_origins = settings.allowed_origins
    if raw_origins == "*":
        origins: list[str] = ["*"]
    else:
        origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health_router)
    app.include_router(admin_router)
    app.include_router(facebook_router)
    app.include_router(instagram_router)
    app.include_router(tiktok_router)
    app.include_router(website_router)
    app.include_router(shipping_router)

    # Prometheus metrics exporter
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            should_group_status_codes=False,
            excluded_handlers=["/health", "/static.*", "/metrics"],
        ).instrument(app).expose(app, endpoint="/metrics")
    except Exception as exc:
        logger.warning(f"Could not initialize Prometheus instrumentator: {exc}")

    # Mount static assets (product photos, videos, uploads)
    static_dir = Path(__file__).resolve().parent.parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "uploads").mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    async def serve_admin_dashboard() -> HTMLResponse:
        template_file = Path(__file__).parent / "templates" / "dashboard.html"
        return HTMLResponse(content=template_file.read_text(encoding="utf-8"))

    return app


app = create_app()
