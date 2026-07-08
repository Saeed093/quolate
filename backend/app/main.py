"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

log = logging.getLogger("quolate.startup")

# psycopg async requires the selector loop on Windows (not ProactorEventLoop).
# TODO(cloud): irrelevant on Linux hosts; SelectorEventLoop lacks subprocess
# support, so subprocess-based tools (e.g. Playwright) run via sync API/threads.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _check_db_reachable() -> None:
    """Fail fast if Postgres is unreachable at startup."""
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(
            settings.database_url,
            echo=False,
        )
        async with engine.begin() as conn:
            await asyncio.wait_for(
                conn.execute(text("SELECT 1")),
                timeout=settings.db_preflight_timeout_seconds,
            )
        await engine.dispose()
        log.info("✓ Database is reachable")
    except asyncio.TimeoutError:
        log.critical(
            "✗ Database did not respond within %fs. Is Postgres running? "
            "Check 'docker compose up -d' and DATABASE_URL=%s",
            settings.db_preflight_timeout_seconds,
            settings.database_url,
        )
        raise
    except Exception as exc:
        log.critical(
            "✗ Cannot connect to database at %s: %s. Is Postgres running?",
            settings.database_url,
            exc,
        )
        raise


async def _check_ollama_reachable() -> None:
    """Warn if Ollama is unreachable at startup (non-fatal)."""
    try:
        import httpx

        ollama_base = settings.llm_base_url.replace("/v1", "")
        async with httpx.AsyncClient(
            timeout=settings.ollama_preflight_timeout_seconds
        ) as client:
            resp = await client.get(f"{ollama_base}/api/tags")
            if resp.status_code == 200:
                log.info("✓ Ollama is reachable (%s)", settings.llm_model)
            else:
                log.warning("✗ Ollama responded but may not be healthy (status %d)", resp.status_code)
    except asyncio.TimeoutError:
        log.warning(
            "⚠ Ollama did not respond within %fs. LLM features will be slow or unavailable. "
            "Start with: ollama serve",
            settings.ollama_preflight_timeout_seconds,
        )
    except Exception as exc:
        log.warning("⚠ Cannot reach Ollama at %s: %s", settings.llm_base_url, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Preflight checks: DB is required, Ollama is optional but recommended.
    await _check_db_reachable()
    await _check_ollama_reachable()

    # Start the in-process background job worker (M2+). Skipped in tests where
    # the worker is driven manually.
    worker_handle = None
    scheduler = None
    if settings.run_worker:
        from app.jobs.worker import start_worker
        from app.tenders.scheduler import start_scheduler

        worker_handle = await start_worker()
        scheduler = start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        if worker_handle is not None:
            await worker_handle.stop()


def create_app() -> FastAPI:
    from app.errorlog import register_error_handlers, setup_error_file_logging

    setup_error_file_logging()
    app = FastAPI(title="Quolate API", version="0.1.0", lifespan=lifespan)
    register_error_handlers(app)

    # Compliance audit trail: records each user action into audit_events.
    from app.audit import audit_middleware

    app.middleware("http")(audit_middleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allow_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/status/llm")
    async def llm_status() -> dict:
        from app.llm.gpu import gpu_chat_status

        return await gpu_chat_status()

    from app.api import register_routers

    register_routers(app)

    return app


app = create_app()
