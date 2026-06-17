from fastapi import APIRouter
from backend.src.services.health import get_health_status

health_router = APIRouter(tags=["Health"])


@health_router.get("/health")
def health_check():
    return get_health_status()
