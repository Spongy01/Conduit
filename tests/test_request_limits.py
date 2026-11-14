"""Request size limits: body bytes (middleware, before auth), and prompt
characters / message count (chat handler, after auth + model access, before
rate limiting and budget)."""
import logging
import uuid

import httpx
import pytest
import pytest_asyncio
from prometheus_client import REGISTRY

from gateway.core.database import db as app_db
from gateway.core.providers import PROVIDERS
from gateway.core.redis_client import redis_client
from gateway.main import app
from gateway.api import chat as chat_module
from gateway.core.schema import ChatCompletionRequest, Message
from gateway.policy.request_limits import apply_output_ceiling, get_limit

from tests.test_provider_usage import _run_app, _stop_app
from tests.dummy_providers.openai_dummy import app as openai_app

MODEL = "gpt-4o-limits"


@pytest_asyncio.fixture
async def openai_dummy_url():
    server, task, url = await _run_app(openai_app)
    original_base_url = PROVIDERS["openai"]._base_url
    PROVIDERS["openai"]._base_url = url
    yield url
    PROVIDERS["openai"]._base_url = original_base_url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def app_client():
    # Per-test pool/client: asyncpg and redis connections are bound to the
    # test's own event loop.
    await app_db.connect()
    redis_client.connect()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await app_db.disconnect()
        await redis_client.disconnect()


async def _seed(db_conn, rate_limit=1000, budget_limit=10.0) -> str:
    await db_conn.execute(
        "INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token) VALUES ($1,'openai',0.01,0.02)",
        MODEL,
    )
    api_key = f"sk-lim-{uuid.uuid4().hex[:12]}"
    await db_conn.execute(
        """INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period)
           VALUES ($1, $2, 'Limits Team', $3, $4, $5, 'monthly')""",
        api_key, f"team-{api_key}", [MODEL], rate_limit, budget_limit,
    )
    return api_key


def _payload(messages):
    return {"model": MODEL, "messages": messages, "max_tokens": 20}


def _msg(content):
    return {"role": "user", "content": content}


async def _post(client, api_key, messages):
    return await client.post("/api/v1/chat/completion", json=_payload(messages),
                             headers={"Authorization": f"Bearer {api_key}"})


async def _assert_untouched(db_conn, api_key):
    spend = await db_conn.fetchval("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert float(spend) == 0.0
    assert await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", api_key) == 0


# --- MAX_REQUEST_BYTES ------------------------------------------------------

async def test_oversized_body_rejected_before_auth(app_client, monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "500")
    # No Authorization header at all: a 413 (not 401/422) proves the body
    # check runs before auth and before the handler.
    response = await app_client.post("/api/v1/chat/completion", content=b"x" * 501,
                                     headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large (limit 500 bytes)"}


async def test_oversized_chunked_body_rejected(app_client, monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "500")

    async def chunks():
        for _ in range(10):
            yield b"x" * 100

    response = await app_client.post("/api/v1/chat/completion", content=chunks(),
                                     headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large (limit 500 bytes)"}


async def test_oversized_body_never_reaches_handler(db_conn, app_client, openai_dummy_url, monkeypatch):
    api_key = await _seed(db_conn)
    monkeypatch.setenv("MAX_REQUEST_BYTES", "300")
    response = await _post(app_client, api_key, [_msg("a" * 1000)])
    assert response.status_code == 413
    await _assert_untouched(db_conn, api_key)
    assert _requests_total("http_413") == 0  # handler's metrics never ran


async def test_body_just_under_limit_succeeds(db_conn, app_client, openai_dummy_url, monkeypatch):
    api_key = await _seed(db_conn)
    body_len = len(httpx.Request("POST", "http://t", json=_payload([_msg("hi")])).content)
    monkeypatch.setenv("MAX_REQUEST_BYTES", str(body_len))
    response = await _post(app_client, api_key, [_msg("hi")])
    assert response.status_code == 200


async def test_get_requests_ignore_body_limit(app_client, monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "1")
    assert (await app_client.get("/metrics")).status_code == 200


# --- MAX_PROMPT_CHARS -------------------------------------------------------

async def test_prompt_over_limit_rejected(db_conn, app_client, openai_dummy_url, monkeypatch):
    api_key = await _seed(db_conn)
    monkeypatch.setenv("MAX_PROMPT_CHARS", "100")
    response = await _post(app_client, api_key, [_msg("a" * 60), _msg("b" * 41)])
    assert response.status_code == 413
    assert response.json() == {"detail": "Prompt too large: 101 characters (limit 100)"}
    await _assert_untouched(db_conn, api_key)


async def test_prompt_at_limit_succeeds(db_conn, app_client, openai_dummy_url, monkeypatch):
    api_key = await _seed(db_conn)
    monkeypatch.setenv("MAX_PROMPT_CHARS", "100")
    response = await _post(app_client, api_key, [_msg("a" * 60), _msg("b" * 40)])
    assert response.status_code == 200


# --- MAX_MESSAGES -----------------------------------------------------------

async def test_too_many_messages_rejected(db_conn, app_client, openai_dummy_url, monkeypatch):
    api_key = await _seed(db_conn)
    monkeypatch.setenv("MAX_MESSAGES", "3")
    response = await _post(app_client, api_key, [_msg("hi")] * 4)
    assert response.status_code == 413
    assert response.json() == {"detail": "Too many messages: 4 (limit 3)"}
    await _assert_untouched(db_conn, api_key)


async def test_messages_at_limit_succeed(db_conn, app_client, openai_dummy_url, monkeypatch):
    api_key = await _seed(db_conn)
    monkeypatch.setenv("MAX_MESSAGES", "3")
    response = await _post(app_client, api_key, [_msg("hi")] * 3)
    assert response.status_code == 200


# --- ordering ---------------------------------------------------------------

async def test_bad_key_with_oversized_prompt_gets_401(db_conn, app_client, monkeypatch):
    monkeypatch.setenv("MAX_PROMPT_CHARS", "10")
    monkeypatch.setenv("MAX_MESSAGES", "1")
    response = await _post(app_client, "sk-nope", [_msg("a" * 50)] * 3)
    assert response.status_code == 401


async def test_disallowed_model_gets_403_before_size_check(db_conn, app_client, monkeypatch):
    api_key = await _seed(db_conn)
    monkeypatch.setenv("MAX_PROMPT_CHARS", "10")
    response = await app_client.post(
        "/api/v1/chat/completion",
        json={"model": "not-allowed", "messages": [_msg("a" * 50)]},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 403


async def test_rejected_request_consumes_no_rate_limit_token(db_conn, app_client, openai_dummy_url, monkeypatch):
    # Bucket of exactly 1 request/minute: if the rejected request had taken
    # the token, the following valid request would get 429.
    api_key = await _seed(db_conn, rate_limit=1)
    monkeypatch.setenv("MAX_MESSAGES", "1")
    assert (await _post(app_client, api_key, [_msg("hi")] * 2)).status_code == 413
    assert (await _post(app_client, api_key, [_msg("hi")])).status_code == 200


# --- metrics ----------------------------------------------------------------

def _requests_total(status):
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name == "requests":
            for s in metric.samples:
                if s.name.endswith("_total") and s.labels.get("status") == status:
                    total += s.value
    return total


def _inflight():
    for metric in REGISTRY.collect():
        if metric.name == "inflight_requests":
            return sum(s.value for s in metric.samples)
    return 0.0


async def test_413_recorded_in_metrics_and_inflight_released(db_conn, app_client, openai_dummy_url, monkeypatch):
    api_key = await _seed(db_conn)
    monkeypatch.setenv("MAX_MESSAGES", "1")
    before_total, before_inflight = _requests_total("http_413"), _inflight()
    assert (await _post(app_client, api_key, [_msg("hi")] * 2)).status_code == 413
    assert _requests_total("http_413") == before_total + 1
    assert _inflight() == before_inflight


# --- configuration ----------------------------------------------------------

@pytest.mark.parametrize("raw", ["abc", "0", "-5", "", "1.5"])
def test_invalid_values_fall_back_to_default(monkeypatch, caplog, raw):
    monkeypatch.setenv("MAX_PROMPT_CHARS", raw)
    with caplog.at_level(logging.WARNING):
        assert get_limit("MAX_PROMPT_CHARS") == 100000
    if raw != "":
        assert "MAX_PROMPT_CHARS" in caplog.text


def test_defaults_and_overrides(monkeypatch):
    for name in ("MAX_REQUEST_BYTES", "MAX_PROMPT_CHARS", "MAX_MESSAGES", "MAX_OUTPUT_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    assert get_limit("MAX_OUTPUT_TOKENS") == 4096
    assert get_limit("MAX_REQUEST_BYTES") == 1000000
    assert get_limit("MAX_PROMPT_CHARS") == 100000
    assert get_limit("MAX_MESSAGES") == 200
    monkeypatch.setenv("MAX_MESSAGES", "7")
    assert get_limit("MAX_MESSAGES") == 7


# --- MAX_OUTPUT_TOKENS ------------------------------------------------------

def _req(max_tokens):
    return ChatCompletionRequest(model="m", messages=[Message(role="user", content="hi")], max_tokens=max_tokens)


def test_ceiling_clamps_larger_request(monkeypatch):
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "100")
    request = _req(5000)
    apply_output_ceiling(request)
    assert request.max_tokens == 100


def test_ceiling_leaves_smaller_or_unset_alone(monkeypatch):
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "100")
    small, unset = _req(40), _req(None)
    apply_output_ceiling(small)
    apply_output_ceiling(unset)
    assert small.max_tokens == 40
    assert unset.max_tokens is None  # paid providers keep their own default; Ollama applies the ceiling itself


async def test_handler_clamps_max_tokens_before_routing(db_conn, app_client, openai_dummy_url, monkeypatch):
    api_key = await _seed(db_conn)
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "100")
    seen = {}
    real_route = chat_module.route_request

    async def spy(request, team):
        seen["max_tokens"] = request.max_tokens
        return await real_route(request, team)

    monkeypatch.setattr(chat_module, "route_request", spy)
    response = await app_client.post(
        "/api/v1/chat/completion",
        json={"model": MODEL, "messages": [_msg("hi")], "max_tokens": 999999},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert seen["max_tokens"] == 100
