from fastapi import Header, HTTPException
from gateway.core.team_config import get_team_config

async def authenticate(authorization: str = Header()) -> dict:
    """
    Validates the API key from the Authorization header and returns
    the team's config. Raises 401 if missing/malformed/unknown.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

    api_key = authorization.removeprefix("Bearer ")
    team = await get_team_config(api_key)

    if team is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return team
