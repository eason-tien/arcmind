"""
ArcMind — Heartbeat Routes
Health check and heartbeat endpoints.
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/heartbeat", tags=["heartbeat"])
async def heartbeat():
    """Simple health check endpoint."""
    return {"status": "alive", "service": "arcmind"}


@router.get("/health", tags=["heartbeat"])
async def health():
    """Detailed health check."""
    return {"status": "healthy", "version": "0.9.3"}
