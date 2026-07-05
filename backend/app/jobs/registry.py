"""Job-type -> handler registry.

Handlers are async callables: async def handler(session, payload) -> None.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

Handler = Callable[[AsyncSession, dict], Awaitable[None]]

_REGISTRY: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _REGISTRY[job_type] = fn
        return fn

    return deco


def get_handler(job_type: str) -> Handler | None:
    return _REGISTRY.get(job_type)


def ensure_handlers_loaded() -> None:
    """Import modules that register handlers (side-effect imports)."""
    # Import here to avoid circular imports at module load.
    from app.chat import embed_job  # noqa: F401
    from app.ingestion import library_pipeline, pipeline  # noqa: F401
    from app.tenders import indexer  # noqa: F401
    from app.tenders import jobs as tender_jobs  # noqa: F401
