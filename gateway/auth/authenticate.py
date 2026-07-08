"""Per-team authentication for the chat API, backed by team API keys
(as opposed to auth/admin.py's single shared admin secret)."""
import logging
from fastapi import Header, HTTPException
from gateway.core.team_config import get_team_config
from gateway.core.tracer import tracer

logger = logging.getLogger(__name__)

async def authenticate(authorization: str = Header()) -> dict:
    """
    Validates the API key from the Authorization header and returns
    the team's config. Raises 401 if missing/malformed/unknown.
    """
    with tracer.start_as_current_span("conduit.auth") as span:
        if not authorization.startswith("Bearer "):
            logger.warning("Authentication failed: missing or malformed Authorization header")
            raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")

        api_key = authorization.removeprefix("Bearer ")
        team = await get_team_config(api_key)

        if team is None:
            logger.warning("Authentication failed: invalid API key")
            raise HTTPException(status_code=401, detail="Invalid API key")

        span.set_attribute("team_id", team.get("team_id", ""))
        logger.debug("Authenticated team_id=%s", team.get("team_id"))
        return team
