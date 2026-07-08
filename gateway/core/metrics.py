"""Prometheus metric definitions for the gateway. Every metric the gateway
exposes is defined here as a module-level singleton and nothing else lives
in this file — call sites import this module and call
`metrics.<name>.labels(...)` rather than constructing their own metric
objects, so every metric is registered exactly once against the default
prometheus_client registry that /metrics scrapes."""
from prometheus_client import Counter, Gauge, Histogram

REQUEST_DURATION_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
TIME_TO_FIRST_TOKEN_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

# --- Counters ---

requests_total = Counter(
    "requests_total",
    "Total chat completion requests handled by the gateway, by final outcome.",
    ["team_id", "provider", "model", "status"],
)

provider_requests_total = Counter(
    "provider_requests_total",
    "Total requests attempted against a specific upstream provider.",
    ["provider", "model", "status"],
)

fallback_events_total = Counter(
    "fallback_events_total",
    "Total times routing fell back from one provider to another for a request.",
    ["from_provider", "to_provider", "model"],
)

ratelimit_rejections_total = Counter(
    "ratelimit_rejections_total",
    "Total requests rejected by the per-team rate limiter.",
    ["team_id", "model"],
)

cache_hits_total = Counter(
    "cache_hits_total",
    "Total cache hits.",
    ["cache_type"],
)

cache_misses_total = Counter(
    "cache_misses_total",
    "Total cache misses.",
    ["cache_type"],
)

# --- Gauges ---

inflight_requests = Gauge(
    "inflight_requests",
    "Chat completion requests currently being processed.",
    ["team_id", "provider", "model"],
)

budget_utilization = Gauge(
    "budget_utilization",
    "Ratio of a team's current spend to its budget limit (current_spend / budget_limit).",
    ["team_id"],
)

# --- Histograms ---

request_duration_seconds = Histogram(
    "request_duration_seconds",
    "End-to-end chat completion request duration, from request start to final response.",
    ["team_id", "provider", "model", "status"],
    buckets=REQUEST_DURATION_BUCKETS,
)

provider_latency_seconds = Histogram(
    "provider_latency_seconds",
    "Latency of a single upstream provider attempt.",
    ["provider", "model", "status"],
    buckets=REQUEST_DURATION_BUCKETS,
)

time_to_first_token_seconds = Histogram(
    "time_to_first_token_seconds",
    "Time from request start to the first streamed chunk being yielded.",
    ["provider", "model"],
    buckets=TIME_TO_FIRST_TOKEN_BUCKETS,
)
