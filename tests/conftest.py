import os
import asyncpg
import httpx
import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://conduit:postgres_conduit@localhost:5433/conduit",
)
TEST_APP_URL = os.environ.get("TEST_APP_URL", "http://localhost:8000")
ADMIN_API_KEY = os.environ["ADMIN_API_KEY"]

CREATE_TEAMS_TABLE = """
    CREATE TABLE IF NOT EXISTS teams (
        api_key TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        team_name TEXT NOT NULL,
        allowed_models TEXT[] NOT NULL,
        rate_limit INTEGER NOT NULL,
        budget_limit FLOAT NOT NULL,
        budget_period TEXT NOT NULL DEFAULT 'monthly'
    )
"""

CREATE_MODELS_TABLE = """
    CREATE TABLE IF NOT EXISTS models (
        name TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        cost_per_input_token FLOAT NOT NULL DEFAULT 0.0,
        cost_per_output_token FLOAT NOT NULL DEFAULT 0.0
    )
"""


@pytest_asyncio.fixture(scope="session")
async def db_conn():
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    await conn.execute(CREATE_TEAMS_TABLE)
    await conn.execute(CREATE_MODELS_TABLE)
    yield conn
    await conn.close()


@pytest_asyncio.fixture(autouse=True)
async def truncate_tables(db_conn):
    yield
    await db_conn.execute("TRUNCATE teams, models")


@pytest_asyncio.fixture(scope="session")
async def client():
    async with httpx.AsyncClient(base_url=TEST_APP_URL) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers():
    return {"X-Admin-Key": ADMIN_API_KEY}
