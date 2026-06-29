"""Remove all teams and models from the test database."""
import asyncio
import os

import asyncpg

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://conduit:postgres_conduit@localhost:5433/conduit",
)


async def clear():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        teams_deleted = await conn.fetchval("SELECT COUNT(*) FROM teams")
        models_deleted = await conn.fetchval("SELECT COUNT(*) FROM models")
        await conn.execute("TRUNCATE teams, models")
        print(f"Cleared {teams_deleted} team(s) and {models_deleted} model(s).")
    except asyncpg.UndefinedTableError:
        print("Tables do not exist — nothing to clear.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(clear())
