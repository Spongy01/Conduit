"""Token-bucket rate limiter backed by Redis. The check-and-decrement is
implemented as a Lua script so it runs atomically inside Redis, avoiding a
read-modify-write race between concurrent requests for the same team."""
import logging
import time
from gateway.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# KEYS[1] = ratelimit:team:{team_id} hash storing tokens_remaining/last_refill_time
# ARGV = current_time, capacity (max tokens/requests), fill_rate (tokens per second)
# Returns 1 and consumes a token if one is available, else 0.
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
    """Attempts to consume one token from the team's bucket. Returns True
    if the request is allowed, False if the bucket is empty (caller should
    respond 429)."""
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