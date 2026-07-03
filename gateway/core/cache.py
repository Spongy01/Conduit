"""Redis-backed cache for team configs, sitting in front of the Postgres
source of truth in core/team_config.py. Every function swallows Redis
errors and treats them as a cache miss, so the gateway degrades to
hitting Postgres directly rather than failing requests if Redis is down."""
import logging
from gateway.core.redis_client import redis_client as cache
import json

logger = logging.getLogger(__name__)

async def get_team_config(api_key: str) -> dict | None:
    """Reads a team's cached config hash. Returns None on a cache miss or
    if Redis is unavailable (caller is expected to fall back to the DB)."""
    try:
        team = await cache.hgetall(f"team:{api_key}:config")
        # print(f"In team config, got team: {team}")
        if team:
            logger.debug("Cache hit for team config api_key=%s", api_key)
            # Deserialize allowed_models from JSON string back to list
            if "allowed_models" in team:
                team["allowed_models"] = json.loads(team["allowed_models"])
            return team
        logger.debug("Cache miss for team config api_key=%s", api_key)
        return None
    except Exception as e:
        # If there's an error (e.g., Redis not connected), we can log it or handle it as needed
        logger.warning("Redis unavailable while getting team config api_key=%s: %s", api_key, e)
        return None

async def set_team_config(api_key: str, team_config: dict) -> None:
    """Writes a team config into the cache with a 90s TTL. This is a
    best-effort write-through cache: failures are logged, not raised, since
    the DB remains the source of truth."""
    # check if redis is connected or not
    try:
        # copy team config so the caller's dict isn't mutated by the JSON encoding below
        team_config_copy = team_config.copy()
        # Serialize allowed_models to JSON string for storage in Redis
        # (Redis hashes only store flat string values, not nested lists)
        if "allowed_models" in team_config_copy:
            team_config_copy["allowed_models"] = json.dumps(team_config_copy["allowed_models"])
        await cache.hset(f"team:{api_key}:config", team_config_copy, expire=90)

    except Exception as e:
        # If there's an error (e.g., Redis not connected), we can log it or handle it as needed
        logger.warning("Redis unavailable while setting team config api_key=%s: %s", api_key, e)


async def delete_team_config(api_key: str) -> None:
    """Invalidates a team's cached config, e.g. after an update or revoke,
    so the next read is forced back to the database."""
    try:
        await cache.delete(f"team:{api_key}:config")
    except Exception as e:
        # If there's an error (e.g., Redis not connected), we can log it or handle it as needed
        logger.warning("Redis unavailable while deleting team config api_key=%s: %s", api_key, e)