# Conduit

A self-hosted LLM gateway for teams — one API, any provider, full control.

---

## The Problem

When a team starts using LLMs, the usual path is: each developer gets their own API key, calls providers directly, and nobody knows what's being spent or on which models. As usage grows, this becomes a mess — keys scattered across codebases, no way to enforce that a team only uses approved models, and a billing surprise at the end of the month.

Conduit sits in front of your LLM providers and solves this. Teams get a single API key that routes through the gateway. An admin controls which models each team can access, sets rate limits, and enforces spending budgets — all without touching provider credentials.

---

## Architecture

A request flows through four layers:

```
Client Request
     │
     ▼
┌─────────────┐
│     Auth    │  Validates the Bearer API key against the teams table
│             │  (Redis-cached, Postgres-backed)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Policy    │  Model access check, per-team rate limit (Redis token
│             │  bucket), and per-attempt budget reservation
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Router    │  Calls the requested model; on a retryable failure,
│             │  falls back to another provider (same tier, or a lower
│             │  tier if allowed) until one succeeds
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Provider   │  Translates the request and calls the upstream LLM API
└─────────────┘
```

**Stack:**
- **FastAPI** — async API server
- **PostgreSQL** — stores teams, models, and budget reservations (source of truth)
- **Redis** — team config caching and the per-team rate limiter's token bucket
- **asyncpg** — async PostgreSQL driver with connection pooling
- **httpx** — async HTTP client for provider calls

---

## Features

### Implemented
- **Multi-provider support** — OpenAI, Anthropic (Claude), Google Gemini, and Ollama (local models) via a common `BaseProvider` interface
- **Per-team API keys** — each team authenticates with a Bearer token; keys are managed via the Admin API
- **Model access control** — teams can only call models explicitly added to their `allowed_models` list
- **Streaming + non-streaming** — both modes supported; upstream errors surface as an HTTP error before any bytes are streamed, rather than mid-stream
- **Tiered fallback routing** — `allow_fallback` retries a request on another provider after a retryable failure (429/5xx or connection error); `allow_tier_downgrade` additionally allows dropping to a lower capability tier if no same-tier candidate is left. Non-retryable errors (400/401/403/422) are never retried
- **Rate limiting** — per-team requests-per-minute cap enforced with a Redis-backed token bucket (atomic via a Lua script); returns `429` with a `Retry-After` header
- **Budget enforcement** — cost is estimated and reserved against a team's `budget_limit` before every provider attempt, then reconciled against real token usage once the call completes; failed attempts release their reservation so fallback doesn't double-charge. (Automatic `budget_period` resets are not implemented yet — `current_spend` only ever decreases via settlement/release.)
- **Redis-backed team config cache** — reads go through Redis (90s TTL) in front of Postgres; the gateway degrades to hitting Postgres directly if Redis is unavailable
- **Admin API** — full CRUD for teams and models; protected by a separate admin key
- **Cost & tier metadata** — models store `cost_per_input_token`/`cost_per_output_token` (for budget calculations) and a `tier` (for fallback ranking)
- **Integration tests** — tests run against a real, running gateway instance backed by Postgres, Redis, and dummy provider servers (no mocks)

### Planned
- **Automatic budget period resets** — `budget_period` (daily/monthly) is stored per team but not yet enforced; spend currently only resets via manual intervention
- **Redis response caching** — cache identical requests to reduce upstream API calls and cost
- **Usage logging & dashboard** — persist token counts and cost per request to Postgres for audit and per-team reporting

---

## Getting Started

### Prerequisites
- Docker and Docker Compose
- Python 3.11+
- Provider API keys for whichever providers you want to enable

### 1. Clone and configure

```bash
git clone https://github.com/your-username/conduit.git
cd conduit
```

Copy `.env.example` to `.env` and fill in real provider keys:

```bash
cp .env.example .env
```

`OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, and `GEMINI_BASE_URL` are also read (defaulting to each provider's real API) — mainly useful for pointing at the dummy provider servers under `tests/dummy_providers` during local development.

### 2. Start everything

```bash
docker compose -f infra/docker-compose.yaml up -d --build
# Gateway (:8000), Postgres, Redis, Prometheus, Grafana, otel-collector, Tempo
```

The `gateway` service builds from `infra/Dockerfile` and reads `.env` (via `env_file`); `DATABASE_URL`, `REDIS_HOST`, and `OTEL_EXPORTER_OTLP_ENDPOINT` are pinned in `infra/docker-compose.yaml` to the other compose services, so `.env` only needs to carry provider keys and `ADMIN_API_KEY`.

### 3. Run the server without Docker (optional)

For hot-reload during development, run the gateway directly against the Postgres/Redis containers instead (exposed on `localhost:5432`/`localhost:6379`):

```bash
pip install -r requirements.txt
set -a; source .env; set +a
uvicorn gateway.main:app --reload
```

### 4. Create a model and a team

```bash
# Register a model (tier ranks capability for fallback: higher = more capable)
curl -X POST http://localhost:8000/admin/v1/models \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "gpt-4o", "provider": "openai", "cost_per_input_token": 0.0000025, "cost_per_output_token": 0.00001, "tier": 4}'

# Create a team
curl -X POST http://localhost:8000/admin/v1/teams \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "team-key-abc", "team_id": "team-1", "team_name": "Backend Team", "allowed_models": ["gpt-4o"], "rate_limit": 100, "budget_limit": 50.0, "budget_period": "monthly"}'
```

### 5. Make a request

```bash
curl -X POST http://localhost:8000/api/v1/chat/completion \
  -H "Authorization: Bearer team-key-abc" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello!"}], "allow_fallback": true}'
```

---

## Admin API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/v1/teams` | Create a team |
| `PATCH` | `/admin/v1/teams/{api_key}` | Update team config |
| `DELETE` | `/admin/v1/teams/{api_key}` | Revoke a team |
| `POST` | `/admin/v1/models` | Register a model |
| `PATCH` | `/admin/v1/models/{model_name}` | Update model metadata |
| `DELETE` | `/admin/v1/models/{model_name}` | Remove a model |

All admin endpoints require the `X-Admin-Key` header.

---

## Running Tests

The test suite is a black-box integration suite: it drives a running gateway instance over HTTP, so Postgres, Redis, the dummy provider servers, and the app itself all need to be up first. The dummy providers run on the host and need to be reachable at `localhost:8001-8004`, so run the gateway on the host too (not the containerized `gateway` service) for this workflow.

```bash
# 1. Postgres + Redis (skip the gateway/observability services)
docker compose -f infra/docker-compose.yaml up -d postgres redis

# 2. Dummy provider servers (stand in for OpenAI/Anthropic/Gemini/Ollama)
python tests/dummy_providers/run_all.py &

# 3. The gateway itself, pointed at the test env
DATABASE_URL=postgresql://conduit:postgres_conduit@localhost:5432/conduit \
ADMIN_API_KEY=test-admin-key \
OPENAI_BASE_URL=http://localhost:8001 ANTHROPIC_BASE_URL=http://localhost:8002 GEMINI_BASE_URL=http://localhost:8003 \
OPENAI_API_KEY=dummy ANTHROPIC_API_KEY=dummy GEMINI_API_KEY=dummy \
uvicorn gateway.main:app --port 8000 &

# 4. Run the tests
ADMIN_API_KEY=test-admin-key pytest
```

`tests/conftest.py` creates/truncates the `teams`, `models`, and `reservations` tables around each test. `tests/loadtest/locustfile.py` and `tests/seed_db.py` are available for load testing against a seeded instance.

---

## Roadmap

- [ ] **Automatic budget period resets** — daily/monthly rollover of `current_spend` based on each team's `budget_period`
- [ ] **Redis response caching** — cache identical requests to cut upstream calls and cost
- [ ] **Usage dashboard** — per-team spend and request volume reporting, backed by persisted per-request usage logs
- [ ] **Fix reservation constraint misattribution** — `create_team`'s duplicate-key error always blames `api_key`, even when `team_id` was the actual unique constraint that collided
