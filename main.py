from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api_router import api_router
from src.core.database import Base, engine
from src.core.exceptions import register_exception_handlers
import os
from src.core.config import settings

from src.core.logger import get_logger

logger = get_logger(__name__)

# -----------------------------
# Lifespan (Startup + Shutdown)
# -----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info(" Starting Orion Backend...")
    
    # DB init
    Base.metadata.create_all(bind=engine)

    # Print all routes
    logger.info(" Registered Routes:")
    for route in app.routes:
        if hasattr(route, "methods"):
            logger.info(f"{list(route.methods)} -> {route.path}")

    yield

    logger.info("Shutting down Orion Backend...")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Orion Backend API",
        version="1.0.0",
        description="AI-driven backend platform",
        lifespan=lifespan   # ✅ NEW
    )
    register_exception_handlers(app)
    # -----------------------------
    # Middleware (CORS)
    # -----------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------
    # Include API Router
    # -----------------------------
    app.include_router(api_router)

    # -----------------------------
    # Health Check
    # -----------------------------
    @app.get("/")
    def root():
        return {
            "message": "Orion Backend is running 🚀",
            "docs": "/docs",
            "api_base": "/api/v1"
        }

    return app


app = create_app()



if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)