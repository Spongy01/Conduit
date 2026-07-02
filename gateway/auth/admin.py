import logging
import os
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

async def require_admin(x_admin_key: str = Header()) -> None:
    if x_admin_key != os.environ["ADMIN_API_KEY"]:
        logger.warning("Admin authentication failed: invalid admin key")
        raise HTTPException(status_code=401, detail="Invalid admin key")