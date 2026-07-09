import os

import redis.asyncio as redis

#create a base object
class RedisClient:
    """Thin async wrapper around a redis-py client, exposing just the
    string/hash operations the gateway needs (team config cache, rate
    limiter). decode_responses=True means values come back as str, not bytes."""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self.client = None

    def connect(self):
        """Creates the underlying redis-py client and its connection pool.
        Must be called before any other method (see main.py's lifespan)."""
        self.client = redis.Redis(host=self.host, port=self.port, db=self.db, decode_responses=True, max_connections=10)

    async def disconnect(self):
        """Closes the client's connection pool on application shutdown."""
        if self.client:
            await self.client.aclose()


    def get_client(self):
        """Returns the connected redis-py client, or raises if connect()
        hasn't been called yet."""
        if self.client is None:
            # print("Redis client is not connected. Call connect() first.")
            raise Exception("Redis client is not connected. Call connect() first.")
        return self.client

    async def set(self, key: str, value: str, expire: int = None):
        """Sets a string key, optionally with a TTL in seconds."""
        client = self.get_client()
        if expire:
            await client.set(key, value, ex=expire)
        else:
            await client.set(key, value)

    async def get(self, key: str):
        """Gets a string key's value, or None if it doesn't exist."""
        client = self.get_client()
        return await client.get(key)

    # make hget set method and get method
    async def hset(self, key:str, value: dict, expire: int = None):
        """Sets multiple fields on a hash key in one call, optionally
        (re-)applying a TTL to the whole hash afterward."""
        client = self.get_client()
        await client.hset(key, mapping=value)
        if expire:
            await client.expire(key, expire)

    async def hgetall(self, key:str):
        """Returns all fields of a hash key as a dict (empty if missing)."""
        client = self.get_client()
        # print(f"Getting all fields for key: {key}")
        return await client.hgetall(key)

    async def hget(self, key:str, field:str):
        """Returns a single field from a hash key, or None if missing."""
        client = self.get_client()
        return await client.hget(key, field)


# when using compose, set REDIS_HOST=redis rather than localhost
redis_client = RedisClient(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", 6379)),
)