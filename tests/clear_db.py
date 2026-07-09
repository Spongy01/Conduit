"""Remove all teams and models from the test database."""
import asyncio
import os

import asyncpg

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://conduit:postgres_conduit@localhost:5432/conduit",
)


async def clear():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        teams_deleted = await conn.fetchval("SELECT COUNT(*) FROM teams")
        models_deleted = await conn.fetchval("SELECT COUNT(*) FROM models")
        reservations_deleted = await conn.fetchval("SELECT COUNT(*) FROM reservations")
        # reservations has a foreign key on teams, so it must be truncated
        # in the same statement (or CASCADE'd) — truncating teams alone
        # raises FeatureNotSupportedError.
        await conn.execute("TRUNCATE reservations, teams, models")
        print(f"Cleared {teams_deleted} team(s), {models_deleted} model(s), and {reservations_deleted} reservation(s).")
    except asyncpg.UndefinedTableError:
        print("Tables do not exist — nothing to clear.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(clear())
