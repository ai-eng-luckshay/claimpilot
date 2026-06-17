import psycopg2
from backend.src.config.app_settings import get_settings
from backend.src.config.logger_config import error_logger, application_logger

settings = get_settings()


def get_health_status() -> dict:
    db_status = _check_db()
    status = "ok" if db_status["connected"] else "degraded"
    application_logger.info("health_check: status=%s db_connected=%s", status, db_status["connected"])
    return {
        "status": status,
        "service": "claimpilot-api",
        "version": "0.2.0",
        "environment": settings.environment,
        "db": db_status,
    }


def _check_db() -> dict:
    try:
        conn = psycopg2.connect(settings.database_url, connect_timeout=3)
        conn.close()
        return {"connected": True}
    except Exception as e:
        error_logger.error("_check_db: database connection failed — %s", e)
        return {"connected": False, "error": str(e)}
