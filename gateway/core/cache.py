import logging
from gateway.core.redis_client import redis_client as cache
import json

logger = logging.getLogger(__name__)

async def get_team_config(api_key: str) -> dict | None:

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
    # check if redis is connected or not
    try:
        # copy team config
        team_config_copy = team_config.copy()
        # Serialize allowed_models to JSON string for storage in Redis
        if "allowed_models" in team_config_copy:
            team_config_copy["allowed_models"] = json.dumps(team_config_copy["allowed_models"])
        await cache.hset(f"team:{api_key}:config", team_config_copy, expire=90)

    except Exception as e:
        # If there's an error (e.g., Redis not connected), we can log it or handle it as needed
        logger.warning("Redis unavailable while setting team config api_key=%s: %s", api_key, e)


async def delete_team_config(api_key: str) -> None:
    try:
        await cache.delete(f"team:{api_key}:config")
    except Exception as e:
        # If there's an error (e.g., Redis not connected), we can log it or handle it as needed
        logger.warning("Redis unavailable while deleting team config api_key=%s: %s", api_key, e)