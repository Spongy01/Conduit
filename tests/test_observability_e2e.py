import httpx

from gateway.main import app


async def test_metrics_endpoint_returns_prometheus_text_format():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

    body = response.text
    for metric_name in [
        "requests_total",
        "provider_requests_total",
        "fallback_events_total",
        "ratelimit_rejections_total",
        "cache_hits_total",
        "cache_misses_total",
        "inflight_requests",
        "budget_utilization",
        "request_duration_seconds",
        "provider_latency_seconds",
        "time_to_first_token_seconds",
    ]:
        assert metric_name in body, f"{metric_name} missing from /metrics output"


import pytest_asyncio

from gateway.core import metrics
from gateway.core.database import db as app_db
from gateway.core.redis_client import redis_client


def _counter_value(counter, **labels):
    return counter.labels(**labels)._value.get()


@pytest_asyncio.fixture
async def db_and_redis():
    """Connects the app's shared db/redis singletons for tests that call
    gateway code directly (route_request, get_team_config, check_rate_limit,
    authenticate) rather than through an HTTP fixture. NOT autouse: tests
    that use `app_client`/`openai_ok`-style fixtures imported from other
    test modules already connect these themselves, and connecting twice in
    the same test leaks a pool/client and makes teardown double-close it —
    so only the tests in this file that need a bare connection request this
    fixture explicitly."""
    await app_db.connect()
    redis_client.connect()
    yield
    await app_db.disconnect()
    await redis_client.disconnect()


async def test_cache_miss_then_hit_increments_counters(db_and_redis):
    import uuid

    from gateway.core.cache import get_team_config, set_team_config

    # Exercises cache.py directly (not through team_config.py's DB-backed
    # get_team_config): a *separate* pre-existing bug means set_team_config
    # silently fails to write when a team dict carries Postgres's Decimal
    # current_spend (redis-py can't serialize Decimal, and the failure is
    # swallowed by cache.py's own except Exception) — that path can never
    # produce a real cache hit today. Out of scope to fix here; testing
    # cache.py's hit/miss counting with plain JSON-safe data sidesteps it
    # and is a more precise test of exactly what this task instruments.
    api_key = f"sk-obs-cache-{uuid.uuid4().hex[:12]}"
    team_config = {
        "team_id": f"team-{api_key}",
        "team_name": "Obs Cache Team",
        "allowed_models": [{"name": "obs-cache-model", "provider": "openai", "tier": 1}],
        "rate_limit": "100",
        "budget_limit": "50.0",
        "budget_period": "monthly",
    }

    misses_before = _counter_value(metrics.cache_misses_total, cache_type="team_config")
    hits_before = _counter_value(metrics.cache_hits_total, cache_type="team_config")

    miss = await get_team_config(api_key)  # miss: nothing cached yet
    assert miss is None
    assert _counter_value(metrics.cache_misses_total, cache_type="team_config") == misses_before + 1

    await set_team_config(api_key, team_config)

    hit = await get_team_config(api_key)  # hit: cached by the call above
    assert hit is not None
    assert hit["team_id"] == team_config["team_id"]
    assert _counter_value(metrics.cache_hits_total, cache_type="team_config") == hits_before + 1


async def test_ratelimit_rejection_increments_counter_and_emits_span(db_conn, db_and_redis, span_exporter):
    import uuid

    from gateway.policy.rate_limiter import check_rate_limit

    # A unique team_id per run: the rate limiter's Redis bucket has no TTL
    # and nothing truncates Redis state between tests the way db_conn
    # truncates Postgres tables, so a literal fixed team_id would see an
    # already-exhausted bucket left over from a previous run in the same
    # Redis instance.
    team_id = f"team-obs-rl-{uuid.uuid4().hex[:12]}"

    before = _counter_value(metrics.ratelimit_rejections_total, team_id=team_id, model="obs-rl-model")

    allowed_1 = await check_rate_limit(team_id=team_id, capacity=1, fill_rate=0.0, model="obs-rl-model")
    assert allowed_1 is True
    allowed_2 = await check_rate_limit(team_id=team_id, capacity=1, fill_rate=0.0, model="obs-rl-model")
    assert allowed_2 is False

    assert _counter_value(metrics.ratelimit_rejections_total, team_id=team_id, model="obs-rl-model") == before + 1

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "conduit.rate_limit"]
    assert len(spans) == 2
    assert spans[0].attributes["team_id"] == team_id
    assert spans[0].attributes["allowed"] is True
    assert spans[1].attributes["allowed"] is False


async def test_model_access_emits_span_with_attributes(span_exporter):
    from fastapi import HTTPException

    from gateway.core.schema import ChatCompletionRequest, Message
    from gateway.policy.model_access import raise_if_model_not_allowed

    team = {"allowed_models": [{"name": "obs-allowed-model", "provider": "openai"}]}
    request = ChatCompletionRequest(
        model="obs-allowed-model", messages=[Message(role="user", content="hi")]
    )

    raise_if_model_not_allowed(request, team)  # allowed: no raise

    denied_request = ChatCompletionRequest(
        model="obs-denied-model", messages=[Message(role="user", content="hi")]
    )
    try:
        raise_if_model_not_allowed(denied_request, team)
        assert False, "expected HTTPException"
    except HTTPException as e:
        assert e.status_code == 403

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "conduit.model_access"]
    assert len(spans) == 2
    assert spans[0].attributes["model_requested"] == "obs-allowed-model"
    assert spans[0].attributes["allowed"] is True
    assert spans[1].attributes["model_requested"] == "obs-denied-model"
    assert spans[1].attributes["allowed"] is False
