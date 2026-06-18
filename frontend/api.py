import httpx
from config import API_URL, IS_DEV

def _timeout(prod: float) -> float | None:
    return None if IS_DEV else prod


def call_health() -> dict | None:
    try:
        r = httpx.get(f"{API_URL}/api/health", timeout=_timeout(10))
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def submit_claim(payload: dict) -> tuple[int, dict]:
    try:
        r = httpx.post(f"{API_URL}/api/claims", json=payload, timeout=_timeout(180))
        return r.status_code, r.json()
    except Exception as e:
        return 500, {"detail": str(e)}


def fetch_claims(member_id: str | None) -> tuple[int, list]:
    params = {"member_id": member_id} if member_id else {}
    try:
        r = httpx.get(f"{API_URL}/api/claims", params=params, timeout=_timeout(15))
        return r.status_code, r.json()
    except Exception as e:
        return 500, [{"detail": str(e)}]


def fetch_claim(claim_id: str) -> tuple[int, dict]:
    try:
        r = httpx.get(f"{API_URL}/api/claims/{claim_id}", timeout=_timeout(15))
        return r.status_code, r.json()
    except Exception as e:
        return 500, {"detail": str(e)}
