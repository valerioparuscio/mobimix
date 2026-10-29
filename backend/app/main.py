import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import config
from app.api.routes import router
from app.data.loader import get_catalog

logger = logging.getLogger("mobimix")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Fail fast on inconsistent data files instead of on the first request.
    catalog = get_catalog()
    logger.info(
        "reference data %s loaded from %s (%d options)",
        catalog.version,
        catalog.data_dir,
        len(catalog.options),
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="MobiMix Personal API",
        description="Personal mobility portfolio advisor.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    static = config.static_dir()
    if static is not None:
        # Last, so that the API and its documentation take their paths first.
        app.mount("/", StaticFiles(directory=static, html=True), name="web")
    return app


app = create_app()
