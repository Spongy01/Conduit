"""FastAPI application entrypoint: wires up routers, observability
(OpenTelemetry tracing + Prometheus metrics), and manages the lifecycle of
shared connections (Postgres pool, Redis client)."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from gateway.api.chat import router as chat_router
from gateway.api.admin import router as admin_router
from gateway.core import metrics  # noqa: F401 -- importing registers every metric with the default
                                   # registry at startup, so /metrics reports them all even before
                                   # the first request exercises the code path that increments them.
from gateway.core.database import db
from gateway.core.providers import PROVIDERS
from gateway.core.redis_client import redis_client

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Opens the database pool and Redis connection on startup, and closes
    everything (including the OTel tracer provider configured at import
    time below) on shutdown, so every request handler can assume they're
    ready."""
    # Startup code: Initialize the database connection pool
    await db.connect()
    logger.debug("Database connection pool initialized")
    # Startup code: Initialize the Redis client
    redis_client.connect()
    logger.debug("Redis client initialized")

    yield

    # Shutdown code: Close any shared httpx clients held by providers
    for provider in PROVIDERS.values():
        if hasattr(provider, "aclose"):
            await provider.aclose()
    logger.debug("Provider HTTP clients closed")
    # Shutdown code: Close the database connection pool
    await db.disconnect()
    logger.debug("Database connection pool closed")
    # Shutdown code: Close the Redis client
    await redis_client.disconnect()
    logger.debug("Redis client closed")
    # Shutdown code: flush any buffered spans and shut the provider down
    tracer_provider.shutdown()
    logger.debug("Tracer provider shut down")


app = FastAPI(lifespan=lifespan)

# Configure the OTel tracer provider and instrument the app *before* it is
# ever invoked for any ASGI scope -- including "lifespan" itself. Starlette's
# `Starlette.__call__` builds and caches `self.middleware_stack` on its very
# first invocation, and that first invocation is the "lifespan" scope uvicorn
# sends to trigger startup. Instrumenting from inside the `lifespan()`
# context manager above runs too late: the (uninstrumented) stack has
# already been built and cached by then, and that same stale stack is reused
# for every subsequent HTTP request, so no root span is ever created and
# every manual span ends up parentless. Doing it here, right after the app
# is constructed, guarantees it happens first.
resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "conduit-gateway")})
tracer_provider = TracerProvider(resource=resource)
otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
trace.set_tracer_provider(tracer_provider)

FastAPIInstrumentor.instrument_app(app)
AsyncPGInstrumentor().instrument()
RedisInstrumentor().instrument()
HTTPXClientInstrumentor().instrument()
logger.debug("OpenTelemetry tracing configured otlp_endpoint=%s", otlp_endpoint)

app.include_router(chat_router, prefix="/api")    # public chat completion endpoints
app.include_router(admin_router, prefix="/admin")  # admin-key-protected team/model management


@app.get("/metrics")
async def metrics_endpoint():
    """Prometheus scrape endpoint, in text exposition format. A plain route
    (rather than mounting prometheus_client's make_asgi_app()) so a bare
    GET /metrics returns 200 directly instead of Starlette's Mount 307-
    redirecting a no-trailing-slash request to /metrics/."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
