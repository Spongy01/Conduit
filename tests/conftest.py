import os
import asyncpg
import httpx
import pytest
import pytest_asyncio
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# Installed once, at collection time, so every manual span created via
# gateway.core.tracer.tracer during the test session lands here instead of
# being a no-op or (if gateway.main's lifespan ever ran) going to a real
# OTLP collector. OTel only honors the *first* set_tracer_provider() call
# per process, so this must run before anything else has a chance to set one.
test_span_exporter = InMemorySpanExporter()
_test_tracer_provider = TracerProvider(resource=Resource.create({"service.name": "conduit-gateway-test"}))
_test_tracer_provider.add_span_processor(SimpleSpanProcessor(test_span_exporter))
trace.set_tracer_provider(_test_tracer_provider)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://conduit:postgres_conduit@localhost:5432/conduit",
)
TEST_APP_URL = os.environ.get("TEST_APP_URL", "http://localhost:8000")
ADMIN_API_KEY = os.environ["ADMIN_API_KEY"]

CREATE_TEAMS_TABLE = """
    CREATE TABLE IF NOT EXISTS teams (
        api_key TEXT PRIMARY KEY,
        team_id TEXT NOT NULL,
        team_name TEXT NOT NULL,
        allowed_models TEXT[] NOT NULL,
        rate_limit INTEGER NOT NULL,
        budget_limit FLOAT NOT NULL,
        budget_period TEXT NOT NULL DEFAULT 'monthly'
    )
"""

CREATE_MODELS_TABLE = """
    CREATE TABLE IF NOT EXISTS models (
        name TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        cost_per_input_token FLOAT NOT NULL DEFAULT 0.0,
        cost_per_output_token FLOAT NOT NULL DEFAULT 0.0,
        tier INTEGER NOT NULL DEFAULT 1
    )
"""

CREATE_RESERVATIONS_TABLE = """
    CREATE TABLE IF NOT EXISTS reservations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        api_key TEXT REFERENCES teams(api_key),
        reserved_amount NUMERIC(10, 8),
        reserved_at TIMESTAMP NOT NULL DEFAULT now()
    )
"""


@pytest.fixture(autouse=True)
def _clear_spans():
    """Every test starts with an empty span buffer, so span-count/content
    assertions in one test never see spans left over from another."""
    test_span_exporter.clear()
    yield


@pytest.fixture
def span_exporter():
    """Returns the actual InMemorySpanExporter backing the process-wide
    OTel tracer provider set above. Tests must use this fixture rather than
    `from tests.conftest import test_span_exporter`: since tests/ has no
    __init__.py, pytest imports this file as a bare `conftest` module for
    its own fixture loading, while an explicit dotted import resolves as
    the separate module `tests.conftest` — Python doesn't dedupe those by
    file path, so a direct import silently re-executes this file's
    top-level code, producing a second exporter that never receives real
    spans (and a second TracerProvider that OTel's "first set wins" rule
    ignores, logging an "Overriding of current TracerProvider is not
    allowed" warning in the process)."""
    return test_span_exporter


@pytest_asyncio.fixture(autouse=True)
async def db_conn():
    conn = await asyncpg.connect(TEST_DATABASE_URL)
    await conn.execute(CREATE_TEAMS_TABLE)
    await conn.execute(CREATE_MODELS_TABLE)
    await conn.execute(CREATE_RESERVATIONS_TABLE)
    yield conn
    await conn.execute("TRUNCATE reservations, teams, models")
    await conn.close()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(base_url=TEST_APP_URL) as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"X-Admin-Key": ADMIN_API_KEY}


@pytest_asyncio.fixture
async def budget_db():
    from gateway.core.database import Database

    database = Database(dsn=TEST_DATABASE_URL)
    await database.connect()
    yield database
    await database.disconnect()


@pytest_asyncio.fixture
async def team_config_db():
    from gateway.core.database import Database

    database = Database(dsn=TEST_DATABASE_URL)
    await database.connect()
    yield database
    await database.disconnect()
