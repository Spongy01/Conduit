import logging
from fastapi import FastAPI
from gateway.api.chat import router as chat_router
from gateway.api.admin import router as admin_router
from gateway.core.database import db
from contextlib import asynccontextmanager
from gateway.core.redis_client import redis_client

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code: Initialize the database connection pool
    await db.connect()
    logger.debug("Database connection pool initialized")
    # Startup code: Initialize the Redis client
    redis_client.connect()
    logger.debug("Redis client initialized")
    yield
    # Shutdown code: Close the database connection pool
    await db.disconnect()
    logger.debug("Database connection pool closed")
    # Shutdown code: Close the Redis client
    await redis_client.disconnect()
    logger.debug("Redis client closed")


app = FastAPI(lifespan=lifespan)
app.include_router(chat_router, prefix="/api")
app.include_router(admin_router, prefix="/admin")
