"""Health check: is every part the system needs reachable?

Used by Docker to know when the API is ready, and in the demo.
Answers 200 if everything is reachable, 503 (with which part failed) if not.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.db import connect
from app.llm.client import check_ollama
from app.services import queue, storage

router = APIRouter(tags=["health"])


def reachable(check) -> bool:
    try:
        return check() is not False
    except Exception:
        return False


@router.get("/health")
def health() -> JSONResponse:
    parts = {
        "postgres": reachable(lambda: connect().close()),
        "redis": reachable(lambda: queue.client().ping()),
        "storage": reachable(lambda: storage.client().head_bucket(Bucket=storage.STORAGE_BUCKET)),
        "ollama": reachable(check_ollama),
    }
    ok = all(parts.values())
    return JSONResponse({"status": "ok" if ok else "degraded", **parts}, status_code=200 if ok else 503)
