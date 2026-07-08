"""Seed the test database with teams and models for load testing."""
import asyncio
import os
import uuid

import asyncpg

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://conduit:postgres_conduit@localhost:5433/conduit",
)

MODELS = [
    {"name": "gpt-4o", "provider": "openai", "cost_per_input_token": 0.0000025, "cost_per_output_token": 0.00001, "tier": 4},
    {"name": "gpt-4o-mini", "provider": "openai", "cost_per_input_token": 0.00000015, "cost_per_output_token": 0.0000006, "tier": 2},
    {"name": "claude-sonnet-4-6", "provider": "anthropic", "cost_per_input_token": 0.000003, "cost_per_output_token": 0.000015, "tier": 4},
    {"name": "gemini-2.0-flash", "provider": "gemini", "cost_per_input_token": 0.0000001, "cost_per_output_token": 0.0000004, "tier": 2},
]

TEAMS = [
    {
        "api_key": "loadtest-key-alpha-001",
        "team_id": "team-alpha",
        "team_name": "Alpha Load Test Team",
        "allowed_models": ["gpt-4o", "gpt-4o-mini"],
        "rate_limit": 500,
        "budget_limit": 50.0,
        "budget_period": "monthly",
    },
    {
        "api_key": "loadtest-key-beta-002",
        "team_id": "team-beta",
        "team_name": "Beta Load Test Team",
        "allowed_models": ["gpt-4o-mini", "claude-sonnet-4-6"],
        "rate_limit": 450,
        "budget_limit": 100.0,
        "budget_period": "monthly",
    },
    {
        "api_key": "loadtest-key-gamma-003",
        "team_id": "team-gamma",
        "team_name": "Gamma Load Test Team",
        "allowed_models": ["gpt-4o", "claude-sonnet-4-6", "gemini-2.0-flash"],
        "rate_limit": 1000,
        "budget_limit": 200.0,
        "budget_period": "monthly",
    },
]


async def seed():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                api_key TEXT PRIMARY KEY,
                team_id TEXT NOT NULL,
                team_name TEXT NOT NULL,
                allowed_models TEXT[] NOT NULL,
                rate_limit INTEGER NOT NULL,
                budget_limit FLOAT NOT NULL,
                budget_period TEXT NOT NULL DEFAULT 'monthly'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS models (
                name TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                cost_per_input_token FLOAT NOT NULL DEFAULT 0.0,
                cost_per_output_token FLOAT NOT NULL DEFAULT 0.0,
                tier INTEGER NOT NULL DEFAULT 1
            )
        """)

        inserted_models = 0
        for m in MODELS:
            try:
                await conn.execute(
                    "INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token, tier) VALUES ($1, $2, $3, $4, $5)",
                    m["name"], m["provider"], m["cost_per_input_token"], m["cost_per_output_token"], m["tier"],
                )
                inserted_models += 1
            except asyncpg.UniqueViolationError:
                print(f"  [skip] model '{m['name']}' already exists")

        inserted_teams = 0
        for t in TEAMS:
            try:
                await conn.execute(
                    "INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    t["api_key"], t["team_id"], t["team_name"], t["allowed_models"],
                    t["rate_limit"], t["budget_limit"], t["budget_period"],
                )
                inserted_teams += 1
            except asyncpg.UniqueViolationError:
                print(f"  [skip] team '{t['team_id']}' (key {t['api_key']}) already exists")

        print(f"Seeded {inserted_models} model(s) and {inserted_teams} team(s).")
        print("\nTeam API keys for load testing:")
        for t in TEAMS:
            print(f"  {t['team_name']}: {t['api_key']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
