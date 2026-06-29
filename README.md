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
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Policy    │  Checks the requested model is in the team's allowed list
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Router    │  Looks up which provider owns the requested model
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Provider   │  Translates the request and calls the upstream LLM API
└─────────────┘
```

**Stack:**
- **FastAPI** — async API server
- **PostgreSQL** — stores teams, models, and configuration
- **Redis** *(planned)* — rate limit windows and response caching
- **asyncpg** — async PostgreSQL driver with connection pooling
- **httpx** — async HTTP client for provider calls

---

## Features

### Implemented
- **Multi-provider support** — OpenAI, Anthropic (Claude), Google Gemini, and Ollama (local models) via a common `BaseProvider` interface
- **Per-team API keys** — each team authenticates with a Bearer token; keys are managed via the Admin API
- **Model access control** — teams can only call models explicitly added to their `allowed_models` list
- **Streaming + non-streaming** — both modes supported; the gateway handles SSE chunking for streaming responses
- **Admin API** — full CRUD for teams and models; protected by a separate admin key
- **Cost metadata** — models store `cost_per_input_token` and `cost_per_output_token` for downstream budget calculations
- **Integration tests** — tests run against a real PostgreSQL instance via Docker; no mocks

### Planned
- **Rate limiting** — per-team request-per-minute caps enforced using a Redis sliding window
- **Budget enforcement** — track spend per team per period; reject requests once the budget is exhausted; configurable reset periods (daily / monthly)
- **Redis caching** — cache identical requests to reduce upstream API calls and cost
- **Usage logging** — persist token counts and cost per request to PostgreSQL for audit and reporting

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

Create `gateway/.env`:

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...
OLLAMA_BASE_URL=http://localhost:11434   # optional, for local models

DATABASE_URL=postgresql://conduit:postgres_conduit@localhost:5432/conduit
ADMIN_API_KEY=your-secret-admin-key
```

### 2. Start the database

```bash
docker compose -f infra/docker-compose.yaml up -d
```

### 3. Run the server

```bash
pip install -r requirements.txt
uvicorn gateway.main:app --reload
```

### 4. Create a team and a model

```bash
# Register a model
curl -X POST http://localhost:8000/admin/v1/models \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"model_name": "gpt-4o", "provider": "openai", "cost_per_input_token": 0.000005, "cost_per_output_token": 0.000015}'

# Create a team
curl -X POST http://localhost:8000/admin/v1/teams \
  -H "X-Admin-Key: your-secret-admin-key" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "team-key-abc", "team_id": "team-1", "team_name": "Backend Team", "allowed_models": ["gpt-4o"], "rate_limit": 100, "budget_limit": 50.0}'
```

### 5. Make a request

```bash
curl -X POST http://localhost:8000/api/v1/chat/completion \
  -H "Authorization: Bearer team-key-abc" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello!"}]}'
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

Tests require the test database to be running:

```bash
docker compose -f tests/docker-compose.test.yaml up -d
ADMIN_API_KEY=your-secret-admin-key pytest
```

---

## Roadmap

- [ ] **Redis integration** — sliding window rate limiting and request-level caching
- [ ] **Budget enforcement** — real-time spend tracking with configurable period resets; requests blocked when budget is exhausted
- [ ] **Usage dashboard** — per-team spend and request volume reporting
- [ ] **Streaming error handling** — graceful error propagation mid-stream without crashing the SSE connection
