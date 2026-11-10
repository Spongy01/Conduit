import os
from pathlib import Path
from urllib.parse import urlparse

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

# Tests run against their own database so they never wipe the data the
# running gateway uses (the `conduit` DB seeded for demos). The in-process app
# (gateway.core.database.db) reads DATABASE_URL at import time, so point it at
# the test DB here, before any test module imports the gateway.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://conduit:postgres_conduit@localhost:5432/conduit_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
ADMIN_API_KEY = os.environ["ADMIN_API_KEY"]

# Single source of truth for the schema: the same file Postgres runs on a
# fresh volume (infra/init.sql), so tests can't drift from the real tables.
SCHEMA_SQL = (Path(__file__).resolve().parent.parent / "infra" / "init.sql").read_text()


def _test_db_name() -> str:
    return urlparse(TEST_DATABASE_URL).path.lstrip("/")


async def _connect_creating_db_if_missing() -> asyncpg.Connection:
    """Connects to the test database, creating it first if it doesn't exist
    (via the server's maintenance `postgres` database)."""
    try:
        return await asyncpg.connect(TEST_DATABASE_URL)
    except asyncpg.InvalidCatalogNameError:
        maintenance = urlparse(TEST_DATABASE_URL)._replace(path="/postgres").geturl()
        admin_conn = await asyncpg.connect(maintenance)
        try:
            await admin_conn.execute(f'CREATE DATABASE "{_test_db_name()}"')
        except asyncpg.DuplicateDatabaseError:
            pass
        finally:
            await admin_conn.close()
        return await asyncpg.connect(TEST_DATABASE_URL)



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
    # Safety net: the TRUNCATE below must never run against a real database.
    assert _test_db_name().endswith("_test"), (
        f"Refusing to run tests against '{_test_db_name()}': TEST_DATABASE_URL must point at a database whose name ends in '_test'"
    )
    conn = await _connect_creating_db_if_missing()
    await conn.execute(SCHEMA_SQL)
    yield conn
    await conn.execute("TRUNCATE reservations, teams, models")
    await conn.close()


@pytest_asyncio.fixture
async def client():
    """In-process client for the gateway app (no running server needed), backed
    by the test database. DB pool / Redis client are created per test because
    their connections are bound to that test's event loop."""
    from gateway.core.database import db as app_db
    from gateway.core.redis_client import redis_client
    from gateway.main import app

    await app_db.connect()
    redis_client.connect()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await app_db.disconnect()
        await redis_client.disconnect()


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
