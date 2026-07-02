import logging
import time
from gateway.core.redis_client import redis_client

logger = logging.getLogger(__name__)

LUA_SCRIPT = """
local value = redis.call('HGET', KEYS[1], 'tokens_remaining')
local current_time = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local fill_rate = tonumber(ARGV[3])
if not value then 
value = capacity-1
redis.call('HSET', KEYS[1], 'tokens_remaining', value, 'last_refill_time', current_time)
return 1
end
local last_refill_time = redis.call('HGET', KEYS[1], 'last_refill_time')
local tokens = tonumber(value)  -- convert string to number
local elapsed = current_time - last_refill_time
local new_tokens = tokens + (elapsed * fill_rate)
if new_tokens > capacity then new_tokens = capacity end
if new_tokens > 0 then
redis.call('HSET', KEYS[1], 'tokens_remaining', new_tokens-1, 'last_refill_time', current_time)
return 1
else
return 0
end
"""

async def check_rate_limit(team_id: str, capacity: int, fill_rate: float) -> bool:
    key = f"ratelimit:team:{team_id}"
    current_time = time.time()
    
    result = await redis_client.get_client().eval(
        LUA_SCRIPT,
        1,
        key,
        current_time,
        capacity,
        fill_rate,
    )

    logger.debug(
        "Rate limit check team_id=%s capacity=%s fill_rate=%s lua_result=%s",
        team_id, capacity, fill_rate, result,
    )

    return result == 1