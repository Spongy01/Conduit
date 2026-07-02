import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gateway.core.database import db as app_db
from gateway.core.providers import PROVIDERS
from gateway.core.redis_client import redis_client
from gateway.main import app

from tests.test_provider_usage import _run_app, _stop_app
from tests.dummy_providers.openai_dummy import app as openai_app

failing_openai_app = FastAPI()


@failing_openai_app.post("/v1/chat/completions")
async def _fail(request: Request):
    return JSONResponse(status_code=500, content={"error": "simulated upstream failure"})

MODEL_PAYLOAD = {
    "name": "gpt-4o-e2e",
    "provider": "openai",
    "cost_per_input_token": 0.01,
    "cost_per_output_token": 0.02,
}


@pytest_asyncio.fixture
async def openai_dummy_url():
    server, task, url = await _run_app(openai_app)
    original_base_url = PROVIDERS["openai"]._base_url
    PROVIDERS["openai"]._base_url = url
    yield url
    PROVIDERS["openai"]._base_url = original_base_url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def failing_openai_dummy_url():
    server, task, url = await _run_app(failing_openai_app)
    original_base_url = PROVIDERS["openai"]._base_url
    PROVIDERS["openai"]._base_url = url
    yield url
    PROVIDERS["openai"]._base_url = original_base_url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def app_client():
    # pytest-asyncio gives each test its own event loop; asyncpg/redis
    # connections are bound to the loop they were created on, so the pool
    # and client must be (re)created fresh for every test rather than reused
    # as a persistent singleton across tests.
    await app_db.connect()
    redis_client.connect()

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await app_db.disconnect()
        await redis_client.disconnect()


async def _seed_model(db_conn, **overrides):
    payload = {**MODEL_PAYLOAD, **overrides}
    await db_conn.execute(
        """
        INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token)
        VALUES ($1, $2, $3, $4)
        """,
        payload["name"], payload["provider"], payload["cost_per_input_token"], payload["cost_per_output_token"],
    )
    return payload["name"]


async def _seed_team(db_conn, model_name: str, budget_limit: float, rate_limit: int = 1000) -> str:
    api_key = f"sk-e2e-{uuid.uuid4().hex[:12]}"
    await db_conn.execute(
        """
        INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        api_key, f"team-{api_key}", "E2E Team", [model_name], rate_limit, budget_limit, "monthly",
    )
    return api_key


async def _post_chat(client, api_key, model, stream=False):
    return await client.post(
        "/api/v1/chat/completion",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Hello there, this is a test message."}],
            "max_tokens": 20,
            "stream": stream,
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )


async def test_chat_within_budget_settles_actual_cost(db_conn, app_client, openai_dummy_url):
    model_name = await _seed_model(db_conn)
    api_key = await _seed_team(db_conn, model_name, budget_limit=10.0)

    response = await _post_chat(app_client, api_key, model_name)

    assert response.status_code == 200
    body = response.json()
    assert body["is_final"] is True
    assert body["usage"]["prompt_tokens"] > 0
    assert body["usage"]["completion_tokens"] > 0

    expected_cost = (
        body["usage"]["prompt_tokens"] * MODEL_PAYLOAD["cost_per_input_token"]
        + body["usage"]["completion_tokens"] * MODEL_PAYLOAD["cost_per_output_token"]
    )

    team_row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert float(team_row["current_spend"]) == pytest.approx(expected_cost)

    reservation_count = await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", api_key)
    assert reservation_count == 0


async def test_chat_over_budget_returns_402_and_no_dangling_reservation(db_conn, app_client, openai_dummy_url):
    model_name = await _seed_model(db_conn)
    api_key = await _seed_team(db_conn, model_name, budget_limit=0.0001)

    response = await _post_chat(app_client, api_key, model_name)

    assert response.status_code == 402

    reservation_count = await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", api_key)
    assert reservation_count == 0

    team_row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert float(team_row["current_spend"]) == pytest.approx(0.0)


async def test_chat_provider_failure_refunds_reservation(db_conn, app_client, failing_openai_dummy_url):
    model_name = await _seed_model(db_conn)
    api_key = await _seed_team(db_conn, model_name, budget_limit=10.0)

    response = await _post_chat(app_client, api_key, model_name)

    assert response.status_code == 500

    reservation_count = await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", api_key)
    assert reservation_count == 0

    team_row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert float(team_row["current_spend"]) == pytest.approx(0.0)
