from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
import time

from api_router import api_router
from src.core.database import Base, engine
from src.core.exceptions import register_exception_handlers
import os
from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

_DLOG = Path(__file__).parent / "pipeline_debug.log"

def _mlog(msg):
    with open(_DLOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(" Starting Orion Backend...")
    Base.metadata.create_all(bind=engine)
    _mlog("[MAIN] app started — routes:")
    for route in app.routes:
        if hasattr(route, "methods"):
            _mlog(f"[MAIN]   {list(route.methods)} {route.path}")
    yield
    logger.info("Shutting down Orion Backend...")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Orion Backend API",
        version="1.0.0",
        description="AI-driven backend platform",
        lifespan=lifespan
    )
    register_exception_handlers(app)

    # ── Request logger middleware ──────────────────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        _mlog(f"[HTTP] {request.method} {request.url.path}")
        t0 = time.time()
        response = await call_next(request)
        ms = int((time.time() - t0) * 1000)
        _mlog(f"[HTTP] -> {response.status_code}  ({ms}ms)")
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/")
    def root():
        return {
            "message": "Orion Backend is running",
            "docs": "/docs",
            "api_base": "/api/v1"
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
