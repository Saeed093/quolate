"""Router registration. Each router module exposes `router: APIRouter`."""
from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI

log = logging.getLogger("quolate.api")

# Order matters only for docs grouping.
_ROUTER_MODULES = [
    "app.api.auth",
    "app.api.projects",
    "app.api.suppliers",
    "app.api.bom",
    "app.api.documents",
    "app.api.fields",
    "app.api.matrix",
    "app.api.chat",
    "app.api.tenders",
    "app.api.tender_sources",
    "app.api.saved_filters",
    "app.api.library",
    "app.api.project_library_links",
    "app.api.activity",
]


def register_routers(app: FastAPI) -> None:
    for mod_path in _ROUTER_MODULES:
        try:
            module = importlib.import_module(mod_path)
        except ModuleNotFoundError as exc:
            # Router not yet implemented at this milestone; skip cleanly.
            if exc.name == mod_path:
                log.debug("router %s not present yet", mod_path)
                continue
            raise
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router)
