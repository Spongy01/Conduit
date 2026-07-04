import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from gateway.core.database import db as app_db
from gateway.core.providers import PROVIDERS
from gateway.core.schema import ChatCompletionRequest, Message
from gateway.router.router import route_request, NoProviderAvailableError

from tests.test_provider_usage import _run_app, _stop_app
from tests.dummy_providers.openai_dummy import app as openai_app
from tests.dummy_providers.anthropic_dummy import app as anthropic_app


def _failing_app(status_code: int = 500) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    @app.post("/v1/messages")
    async def _fail(request: Request):
        return JSONResponse(status_code=status_code, content={"error": "simulated upstream failure"})

    return app


@pytest_asyncio.fixture
async def openai_ok():
    server, task, url = await _run_app(openai_app)
    original = PROVIDERS["openai"]._base_url
    PROVIDERS["openai"]._base_url = url
    yield url
    PROVIDERS["openai"]._base_url = original
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def anthropic_ok():
    server, task, url = await _run_app(anthropic_app)
    original = PROVIDERS["anthropic"]._base_url
    PROVIDERS["anthropic"]._base_url = url
    yield url
    PROVIDERS["anthropic"]._base_url = original
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def openai_failing(request):
    status_code = getattr(request, "param", 500)
    server, task, url = await _run_app(_failing_app(status_code))
    original = PROVIDERS["openai"]._base_url
    PROVIDERS["openai"]._base_url = url
    yield url
    PROVIDERS["openai"]._base_url = original
    await _stop_app(server, task)


@pytest_asyncio.fixture(autouse=True)
async def _connect_db():
    await app_db.connect()
    yield
    await app_db.disconnect()


async def _seed_model(db_conn, name, provider, tier, cost=0.001):
    await db_conn.execute(
        "INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token, tier) VALUES ($1, $2, $3, $4, $5)",
        name, provider, cost, cost, tier,
    )


async def _seed_team(db_conn, api_key, allowed_models, budget_limit=100.0):
    await db_conn.execute(
        """
        INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        api_key, f"team-{api_key}", "Fallback Team", allowed_models, 1000, budget_limit, "monthly",
    )


def _request(model, allow_fallback=False, allow_tier_downgrade=False):
    return ChatCompletionRequest(
        model=model,
        messages=[Message(role="user", content="Hello there, this is a test message.")],
        max_tokens=20,
        allow_fallback=allow_fallback,
        allow_tier_downgrade=allow_tier_downgrade,
    )


async def _team_dict(api_key):
    from gateway.core.team_config import get_team_config
    return await get_team_config(api_key)


async def test_no_fallback_success_on_first_try(db_conn, openai_ok):
    await _seed_model(db_conn, "gpt-4o-e2e", "openai", tier=4)
    await _seed_team(db_conn, "sk-fb-1", ["gpt-4o-e2e"])
    team = await _team_dict("sk-fb-1")

    generator, reservation_id = await route_request(_request("gpt-4o-e2e"), team)

    responses = [r async for r in generator]
    assert responses[0].model == "gpt-4o-e2e"
    assert reservation_id is not None


async def test_retryable_failure_without_fallback_raises(db_conn, openai_failing):
    await _seed_model(db_conn, "gpt-4o-e2e", "openai", tier=4)
    await _seed_team(db_conn, "sk-fb-2", ["gpt-4o-e2e"])
    team = await _team_dict("sk-fb-2")

    with pytest.raises(HTTPException) as exc_info:
        await route_request(_request("gpt-4o-e2e", allow_fallback=False), team)
    assert exc_info.value.status_code == 500

    reservation_count = await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", "sk-fb-2")
    assert reservation_count == 0


async def test_retryable_failure_falls_back_to_same_tier_different_provider(db_conn, openai_failing, anthropic_ok):
    await _seed_model(db_conn, "gpt-4o-e2e", "openai", tier=4)
    await _seed_model(db_conn, "claude-e2e", "anthropic", tier=4)
    await _seed_team(db_conn, "sk-fb-3", ["gpt-4o-e2e", "claude-e2e"])
    team = await _team_dict("sk-fb-3")

    generator, reservation_id = await route_request(_request("gpt-4o-e2e", allow_fallback=True), team)

    responses = [r async for r in generator]
    assert responses[0].model == "claude-e2e"

    # the failed openai attempt's reservation was released; only the winning
    # attempt's reservation is outstanding (to be settled by chat.py)
    reservation_row = await db_conn.fetchrow("SELECT * FROM reservations WHERE id = $1", reservation_id)
    assert reservation_row is not None
    count = await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", "sk-fb-3")
    assert count == 1


@pytest.mark.parametrize("openai_failing", [400], indirect=True)
async def test_non_retryable_failure_raises_immediately_even_with_fallback_allowed(db_conn, openai_failing, anthropic_ok):
    await _seed_model(db_conn, "gpt-4o-e2e", "openai", tier=4)
    await _seed_model(db_conn, "claude-e2e", "anthropic", tier=4)
    await _seed_team(db_conn, "sk-fb-4", ["gpt-4o-e2e", "claude-e2e"])
    team = await _team_dict("sk-fb-4")

    with pytest.raises(HTTPException) as exc_info:
        await route_request(_request("gpt-4o-e2e", allow_fallback=True), team)
    assert exc_info.value.status_code == 400

    reservation_count = await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", "sk-fb-4")
    assert reservation_count == 0


async def test_tier_downgrade_used_only_when_allowed(db_conn, openai_failing):
    await _seed_model(db_conn, "gpt-4o-e2e", "openai", tier=4)
    await _seed_model(db_conn, "llama-e2e", "ollama", tier=2)
    await _seed_team(db_conn, "sk-fb-5", ["gpt-4o-e2e", "llama-e2e"])
    team = await _team_dict("sk-fb-5")

    with pytest.raises(NoProviderAvailableError):
        await route_request(_request("gpt-4o-e2e", allow_fallback=True, allow_tier_downgrade=False), team)


async def test_budget_exceeded_is_soft_skipped_and_falls_back(db_conn, openai_ok, anthropic_ok):
    await _seed_model(db_conn, "gpt-4o-e2e", "openai", tier=4, cost=1000.0)
    await _seed_model(db_conn, "claude-e2e", "anthropic", tier=4, cost=0.0001)
    await _seed_team(db_conn, "sk-fb-6", ["gpt-4o-e2e", "claude-e2e"], budget_limit=1.0)
    team = await _team_dict("sk-fb-6")

    # gpt-4o-e2e's estimated cost blows the $1 budget outright, so the very
    # first "attempt" never calls a provider — it's a budget skip, not a
    # provider failure. allow_fallback must still be True for a fallback
    # candidate list to be considered after a skip.
    generator, reservation_id = await route_request(_request("gpt-4o-e2e", allow_fallback=True), team)

    responses = [r async for r in generator]
    assert responses[0].model == "claude-e2e"


async def test_all_candidates_budget_exceeded_raises_value_error(db_conn, openai_ok, anthropic_ok):
    await _seed_model(db_conn, "gpt-4o-e2e", "openai", tier=4, cost=1000.0)
    await _seed_model(db_conn, "claude-e2e", "anthropic", tier=4, cost=1000.0)
    await _seed_team(db_conn, "sk-fb-7", ["gpt-4o-e2e", "claude-e2e"], budget_limit=1.0)
    team = await _team_dict("sk-fb-7")

    with pytest.raises(ValueError, match="Budget limit exceeded"):
        await route_request(_request("gpt-4o-e2e", allow_fallback=True), team)
