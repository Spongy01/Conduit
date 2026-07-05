"""One-off migration: adds the models.tier column (used by fallback routing
to rank models within a capability class) and backfills it for the models
already known to this deployment. Run once against the real database:

    DATABASE_URL=postgresql://... python scripts/migrate_add_tier.py
"""
import asyncio
import os

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://conduit:postgres_conduit@localhost:5432/conduit",
)

# name -> tier. Anything not listed here keeps the column default (1).
TIER_BACKFILL = {
    "gpt-4o": 4,
    "claude-3-5-sonnet": 4,
    "claude-sonnet-4-6": 4,
    "gpt-4o-mini": 2,
    "gemini-2.0-flash": 2,
    "llama3": 2,
}


async def migrate():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(
            "ALTER TABLE models ADD COLUMN IF NOT EXISTS tier INTEGER NOT NULL DEFAULT 1"
        )
        for name, tier in TIER_BACKFILL.items():
            result = await conn.execute(
                "UPDATE models SET tier = $1 WHERE name = $2", tier, name
            )
            print(f"  {name}: {result}")
        print("Migration complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
