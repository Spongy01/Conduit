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
