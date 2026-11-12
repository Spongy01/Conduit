"""Admin authentication: a single shared secret (ADMIN_API_KEY) gates all
admin endpoints, as opposed to the per-team API keys used for chat."""
import logging
import os
from fastapi import Header, HTTPException
import secrets

logger = logging.getLogger(__name__)

async def require_admin(x_admin_key: str = Header()) -> None:
    """FastAPI dependency that raises 401 unless X-Admin-Key matches the
    server's configured ADMIN_API_KEY. Returns None on success."""
    expected = os.environ["ADMIN_API_KEY"]
    if not secrets.compare_digest(x_admin_key.encode(), expected.encode()):
        logger.warning("Admin authentication failed: invalid admin key")
        raise HTTPException(status_code=401, detail="Invalid admin key")