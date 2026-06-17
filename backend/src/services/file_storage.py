"""Save raw document files to local disk and generate access URLs."""
import base64
import re
from pathlib import Path

from backend.src.config.app_settings import get_settings
from backend.src.config.logger_config import error_logger

_UPLOAD_ROOT = Path(__file__).parent.parent.parent / "uploads"


def _safe_filename(index: int, original_name: str) -> str:
    """Return a safe, index-prefixed filename."""
    name = re.sub(r"[^\w.\-]", "_", original_name)
    return f"{index:02d}_{name}"


def save_document(claim_id: str, index: int, file_name: str, file_data_b64: str) -> str:
    """
    Decode base64 file data and write to uploads/claims/{claim_id}/.
    Returns the relative path from the upload root (used as DB value and URL suffix).
    """
    claim_dir = _UPLOAD_ROOT / "claims" / claim_id
    claim_dir.mkdir(parents=True, exist_ok=True)

    safe_name = _safe_filename(index, file_name)
    file_path = claim_dir / safe_name

    try:
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(file_data_b64))
    except Exception as e:
        error_logger.error("save_document: failed to write %s — %s", file_path, e)
        raise

    error_logger.info("save_document: saved %s → %s", file_name, file_path)
    return f"claims/{claim_id}/{safe_name}"


def get_file_url(relative_path: str) -> str:
    """Build the full URL to access a stored file via the FastAPI static mount."""
    settings = get_settings()
    return f"{settings.api_base_url}/uploads/{relative_path}"
