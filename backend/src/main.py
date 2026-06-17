from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from backend.src.config import logger_config
from backend.src.middleware.logger_middleware import LoggerConfigMiddleware
from backend.src.services.policy import load_policy
from backend.src.controllers.health import health_router
from backend.src.controllers.claims import claims_router

_UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger_config.start_logging_listener()
    logger_config.application_logger.info(f"ClaimPilot API starting up — {app.version}")
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        load_policy()
        logger_config.application_logger.info("Policy loaded successfully")
    except Exception as e:
        logger_config.error_logger.error("Failed to load policy on startup: %s", e)
    yield
    logger_config.application_logger.info("ClaimPilot API shutting down")
    logger_config.stop_logging_listener()


app = FastAPI(
    title="ClaimPilot API",
    description="AI-powered health insurance claims processing for Plum",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(BaseHTTPMiddleware, dispatch=LoggerConfigMiddleware())
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve raw uploaded documents at /uploads/<claim_id>/<filename>
app.mount("/uploads", StaticFiles(directory=str(_UPLOAD_DIR)), name="uploads")

app.include_router(health_router, prefix="/api")
app.include_router(claims_router, prefix="/api/claims")
