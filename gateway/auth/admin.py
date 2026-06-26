import os
from fastapi import Header, HTTPException

async def require_admin(x_admin_key: str = Header()) -> None:
    if x_admin_key != os.environ["ADMIN_API_KEY"]:
        raise HTTPException(status_code=401, detail="Invalid admin key")