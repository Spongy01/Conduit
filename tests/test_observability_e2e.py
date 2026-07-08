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


async def test_authenticate_emits_span_with_team_id(db_conn, db_and_redis, span_exporter):
    from gateway.auth.authenticate import authenticate

    await db_conn.execute(
        "INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token, tier) "
        "VALUES ($1, $2, $3, $4, $5)",
        "obs-auth-model", "openai", 0.001, 0.001, 1,
    )
    await db_conn.execute(
        "INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        "sk-obs-auth-1", "team-obs-auth-1", "Obs Auth Team", ["obs-auth-model"], 100, 50.0, "monthly",
    )

    team = await authenticate(authorization="Bearer sk-obs-auth-1")
    assert team["team_id"] == "team-obs-auth-1"

    spans = [s for s in span_exporter.get_finished_spans() if s.name == "conduit.auth"]
    assert len(spans) == 1
    assert spans[0].attributes["team_id"] == "team-obs-auth-1"


from tests.test_fallback_e2e import (
    openai_ok, anthropic_ok, openai_failing,
    _seed_model as _fb_seed_model, _seed_team as _fb_seed_team,
    _request as _fb_request, _team_dict as _fb_team_dict,
)


def _histogram_count(histogram, **labels):
    # prometheus_client's Histogram child has no _count attribute; each
    # element of _buckets is a raw (non-cumulative) per-bucket counter, and
    # the total observation count (what the exposition format calls
    # `<name>_count`) is their sum, computed cumulatively only at export time.
    child = histogram.labels(**labels)
    return sum(bucket.get() for bucket in child._buckets)


async def test_router_records_provider_success_metrics(db_conn, db_and_redis, openai_ok):
    await _fb_seed_model(db_conn, "obs-router-success", "openai", tier=4)
    await _fb_seed_team(db_conn, "sk-obs-router-1", ["obs-router-success"])
    team = await _fb_team_dict("sk-obs-router-1")

    from gateway.router.router import route_request

    requests_before = _counter_value(
        metrics.provider_requests_total, provider="openai", model="obs-router-success", status="success"
    )
    latency_count_before = _histogram_count(
        metrics.provider_latency_seconds, provider="openai", model="obs-router-success", status="success"
    )

    generator, reservation_id = await route_request(_fb_request("obs-router-success"), team)
    [r async for r in generator]

    assert _counter_value(
        metrics.provider_requests_total, provider="openai", model="obs-router-success", status="success"
    ) == requests_before + 1
    assert _histogram_count(
        metrics.provider_latency_seconds, provider="openai", model="obs-router-success", status="success"
    ) == latency_count_before + 1


async def test_router_records_fallback_event_and_attempt_spans(db_conn, db_and_redis, openai_failing, anthropic_ok, span_exporter):
    from gateway.router.router import route_request

    await _fb_seed_model(db_conn, "obs-router-2a", "openai", tier=4)
    await _fb_seed_model(db_conn, "obs-router-2b", "anthropic", tier=4)
    await _fb_seed_team(db_conn, "sk-obs-router-2", ["obs-router-2a", "obs-router-2b"])
    team = await _fb_team_dict("sk-obs-router-2")

    fallback_before = _counter_value(
        metrics.fallback_events_total, from_provider="openai", to_provider="anthropic", model="obs-router-2a"
    )

    generator, reservation_id = await route_request(_fb_request("obs-router-2a", allow_fallback=True), team)
    [r async for r in generator]

    assert _counter_value(
        metrics.fallback_events_total, from_provider="openai", to_provider="anthropic", model="obs-router-2a"
    ) == fallback_before + 1

    spans = span_exporter.get_finished_spans()
    assert "conduit.route_request" in [s.name for s in spans]

    attempt_spans = [s for s in spans if s.name == "conduit.provider.attempt"]
    assert len(attempt_spans) == 2
    outcomes = sorted(s.attributes["outcome"] for s in attempt_spans)
    assert outcomes == ["retryable_error", "success"]
    is_fallback_values = sorted(s.attributes["is_fallback"] for s in attempt_spans)
    assert is_fallback_values == [False, True]
    attempt_numbers = sorted(s.attributes["attempt_number"] for s in attempt_spans)
    assert attempt_numbers == [1, 2]
