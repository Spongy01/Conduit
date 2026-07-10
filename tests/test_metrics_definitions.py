from prometheus_client import Counter, Gauge, Histogram

from gateway.core import metrics

REQUEST_BUCKETS = [0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
TTFT_BUCKETS = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]


def test_counters_have_correct_type_and_labels():
    assert isinstance(metrics.requests_total, Counter)
    assert sorted(metrics.requests_total._labelnames) == sorted(["team_id", "provider", "model", "status"])

    assert isinstance(metrics.provider_requests_total, Counter)
    assert sorted(metrics.provider_requests_total._labelnames) == sorted(["provider", "model", "status"])

    assert isinstance(metrics.fallback_events_total, Counter)
    assert sorted(metrics.fallback_events_total._labelnames) == sorted(["from_provider", "to_provider", "model"])

    assert isinstance(metrics.ratelimit_rejections_total, Counter)
    assert sorted(metrics.ratelimit_rejections_total._labelnames) == sorted(["team_id", "model"])

    assert isinstance(metrics.cache_hits_total, Counter)
    assert list(metrics.cache_hits_total._labelnames) == ["cache_type"]

    assert isinstance(metrics.cache_misses_total, Counter)
    assert list(metrics.cache_misses_total._labelnames) == ["cache_type"]


def test_gauges_have_correct_type_and_labels():
    assert isinstance(metrics.inflight_requests, Gauge)
    assert sorted(metrics.inflight_requests._labelnames) == sorted(["team_id", "provider", "model"])

    assert isinstance(metrics.budget_utilization, Gauge)
    assert list(metrics.budget_utilization._labelnames) == ["team_id"]


def test_histograms_have_correct_type_labels_and_buckets():
    assert isinstance(metrics.request_duration_seconds, Histogram)
    assert sorted(metrics.request_duration_seconds._labelnames) == sorted(["team_id", "provider", "model", "status", "stream"])
    assert metrics.request_duration_seconds._upper_bounds[:-1] == REQUEST_BUCKETS

    assert isinstance(metrics.provider_latency_seconds, Histogram)
    assert sorted(metrics.provider_latency_seconds._labelnames) == sorted(["provider", "model", "status", "stream"])
    assert metrics.provider_latency_seconds._upper_bounds[:-1] == REQUEST_BUCKETS

    assert isinstance(metrics.time_to_first_token_seconds, Histogram)
    assert sorted(metrics.time_to_first_token_seconds._labelnames) == sorted(["provider", "model"])
    assert metrics.time_to_first_token_seconds._upper_bounds[:-1] == TTFT_BUCKETS
