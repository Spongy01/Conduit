"""GET /api/v1/models: a team key lists the models it may use."""
import uuid

import httpx
import pytest_asyncio

from gateway.core.database import db as app_db
from gateway.core.redis_client import redis_client
from gateway.main import app


@pytest_asyncio.fixture
async def app_client():
    # Fresh DB pool / Redis client per test: asyncpg and redis connections are
    # bound to the event loop they were created on (one loop per test).
    await app_db.connect()
    redis_client.connect()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await app_db.disconnect()
        await redis_client.disconnect()


async def _seed_model(db_conn, name, provider, tier, cost_in=0.01, cost_out=0.02):
    await db_conn.execute(
        """
        INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token, tier)
        VALUES ($1, $2, $3, $4, $5)
        """,
        name, provider, cost_in, cost_out, tier,
    )


async def _seed_team(db_conn, allowed_models):
    api_key = f"sk-models-{uuid.uuid4().hex[:12]}"
    await db_conn.execute(
        """
        INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        api_key, f"team-{api_key}", "Models Team", allowed_models, 100, 10.0, "monthly",
    )
    return api_key


def _auth(api_key):
    return {"Authorization": f"Bearer {api_key}"}


async def test_lists_only_the_teams_allowed_models(db_conn, app_client):
    await _seed_model(db_conn, "m-zeta", "ollama", tier=2)
    await _seed_model(db_conn, "m-alpha", "openai", tier=4)
    await _seed_model(db_conn, "m-other", "anthropic", tier=3)
    api_key = await _seed_team(db_conn, ["m-zeta", "m-alpha"])

    r = await app_client.get("/api/v1/models", headers=_auth(api_key))

    assert r.status_code == 200
    # sorted by name, and m-other (not allowed for this team) is absent
    assert r.json() == {"models": [
        {"name": "m-alpha", "provider": "openai", "tier": 4},
        {"name": "m-zeta", "provider": "ollama", "tier": 2},
    ]}


async def test_response_has_no_cost_or_team_data(db_conn, app_client):
    await _seed_model(db_conn, "m-priced", "openai", tier=1)
    api_key = await _seed_team(db_conn, ["m-priced"])

    r = await app_client.get("/api/v1/models", headers=_auth(api_key))

    body = r.json()
    assert set(body.keys()) == {"models"}
    assert set(body["models"][0].keys()) == {"name", "provider", "tier"}


async def test_team_with_no_models_gets_empty_list(db_conn, app_client):
    api_key = await _seed_team(db_conn, [])

    r = await app_client.get("/api/v1/models", headers=_auth(api_key))

    assert r.status_code == 200
    assert r.json() == {"models": []}


async def test_invalid_key_returns_401(db_conn, app_client):
    r = await app_client.get("/api/v1/models", headers=_auth("sk-does-not-exist"))
    assert r.status_code == 401


async def test_missing_authorization_header_is_rejected(db_conn, app_client):
    r = await app_client.get("/api/v1/models")
    assert r.status_code in (401, 422)
