from fastapi import FastAPI
from gateway.api.chat import router as chat_router
from gateway.api.admin import router as admin_router
from gateway.core.database import db
from contextlib import asynccontextmanager
from gateway.core.redis_client import redis_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code: Initialize the database connection pool
    await db.connect()
    # Startup code: Initialize the Redis client
    redis_client.connect()
    yield
    # Shutdown code: Close the database connection pool
    await db.disconnect()
    # Shutdown code: Close the Redis client
    await redis_client.disconnect()


app = FastAPI(lifespan=lifespan)
app.include_router(chat_router, prefix="/api")
app.include_router(admin_router, prefix="/admin")
