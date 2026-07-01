import redis.asyncio as redis

#create a base object
class RedisClient:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self.client = None

    def connect(self):
        self.client = redis.Redis(host=self.host, port=self.port, db=self.db, decode_responses=True, max_connections=10)

    async def disconnect(self):
        if self.client:
            await self.client.aclose()


    def get_client(self):
        if self.client is None:
            # print("Redis client is not connected. Call connect() first.")
            raise Exception("Redis client is not connected. Call connect() first.")
        return self.client
    
    async def set(self, key: str, value: str, expire: int = None):
        client = self.get_client()
        if expire:
            await client.set(key, value, ex=expire)
        else:
            await client.set(key, value)

    async def get(self, key: str):
        client = self.get_client()
        return await client.get(key)

    # make hget set method and get method
    async def hset(self, key:str, value: dict, expire: int = None):
        client = self.get_client()
        await client.hset(key, mapping=value)
        if expire:
            await client.expire(key, expire)
    
    async def hgetall(self, key:str):
        client = self.get_client()
        # print(f"Getting all fields for key: {key}")
        return await client.hgetall(key)

    async def hget(self, key:str, field:str):
        client = self.get_client()
        return await client.hget(key, field)


redis_client = RedisClient()                  