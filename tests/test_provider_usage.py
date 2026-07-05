import asyncio
import socket

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from gateway.core.schema import ChatCompletionRequest, Message
from gateway.providers.AnthropicProvider import AnthropicProvider
from gateway.providers.GeminiProvider import GeminiProvider
from gateway.providers.OllamaProvider import OllamaProvider
from gateway.providers.OpenAIProvider import OpenAIProvider
from tests.dummy_providers.anthropic_dummy import app as anthropic_app
from tests.dummy_providers.gemini_dummy import app as gemini_app
from tests.dummy_providers.ollama_dummy import app as ollama_app
from tests.dummy_providers.openai_dummy import app as openai_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _run_app(app):
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    return server, task, f"http://127.0.0.1:{port}"


async def _stop_app(server, task):
    server.should_exit = True
    await task


@pytest_asyncio.fixture
async def openai_server():
    server, task, url = await _run_app(openai_app)
    yield url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def anthropic_server():
    server, task, url = await _run_app(anthropic_app)
    yield url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def gemini_server():
    server, task, url = await _run_app(gemini_app)
    yield url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def ollama_server():
    server, task, url = await _run_app(ollama_app)
    yield url
    await _stop_app(server, task)


def _failing_app(status_code: int) -> FastAPI:
    app = FastAPI()

    @app.post("/{path:path}")
    async def _fail(path: str, request: Request):
        return JSONResponse(status_code=status_code, content={"error": "simulated upstream failure"})

    return app


@pytest_asyncio.fixture
async def failing_openai_server():
    server, task, url = await _run_app(_failing_app(500))
    yield url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def failing_anthropic_server():
    server, task, url = await _run_app(_failing_app(500))
    yield url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def failing_gemini_server():
    server, task, url = await _run_app(_failing_app(500))
    yield url
    await _stop_app(server, task)


@pytest_asyncio.fixture
async def failing_ollama_server():
    server, task, url = await _run_app(_failing_app(500))
    yield url
    await _stop_app(server, task)


def _request(stream: bool, max_tokens: int = 50) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model="dummy-model",
        messages=[Message(role="user", content="Hello there, this is a test message.")],
        stream=stream,
        max_tokens=max_tokens,
    )


async def _collect(provider, request):
    return [r async for r in provider.generate(request)]


# ─── OpenAI ────────────────────────────────────────────────────────────────

async def test_openai_non_streaming_usage(openai_server):
    provider = OpenAIProvider(api_key="dummy")
    provider._base_url = openai_server

    responses = await _collect(provider, _request(stream=False))

    assert len(responses) == 1
    r = responses[0]
    assert r.is_final is True
    assert r.usage.prompt_tokens > 0
    assert r.usage.completion_tokens > 0
    assert r.usage.total_tokens == r.usage.prompt_tokens + r.usage.completion_tokens


async def test_openai_streaming_usage(openai_server):
    provider = OpenAIProvider(api_key="dummy")
    provider._base_url = openai_server

    responses = await _collect(provider, _request(stream=True))

    text_chunks = [r for r in responses if not r.is_final]
    final_chunks = [r for r in responses if r.is_final]

    assert len(final_chunks) == 1
    assert final_chunks[0].delta is None
    assert final_chunks[0].usage.prompt_tokens > 0
    assert final_chunks[0].usage.completion_tokens > 0

    assert text_chunks[0].usage.prompt_tokens > 0
    for chunk in text_chunks[1:]:
        assert chunk.usage.prompt_tokens == 0
        assert chunk.usage.completion_tokens >= 0


# ─── Anthropic ─────────────────────────────────────────────────────────────

async def test_anthropic_non_streaming_usage(anthropic_server):
    provider = AnthropicProvider(api_key="dummy")
    provider._base_url = anthropic_server

    responses = await _collect(provider, _request(stream=False))

    assert len(responses) == 1
    r = responses[0]
    assert r.is_final is True
    assert r.usage.prompt_tokens > 0
    assert r.usage.completion_tokens > 0


async def test_anthropic_streaming_usage(anthropic_server):
    provider = AnthropicProvider(api_key="dummy")
    provider._base_url = anthropic_server

    responses = await _collect(provider, _request(stream=True))

    final_chunks = [r for r in responses if r.is_final]
    text_chunks = [r for r in responses if not r.is_final]

    assert len(final_chunks) == 1
    assert final_chunks[0].usage.completion_tokens > 0
    assert text_chunks[0].usage.prompt_tokens > 0
    for chunk in text_chunks[1:]:
        assert chunk.usage.prompt_tokens == 0


# ─── Gemini ────────────────────────────────────────────────────────────────

async def test_gemini_non_streaming_usage(gemini_server):
    provider = GeminiProvider(api_key="dummy")
    provider.base_url = f"{gemini_server}/v1beta/models"

    responses = await _collect(provider, _request(stream=False))

    assert len(responses) == 1
    r = responses[0]
    assert r.is_final is True
    assert r.usage.prompt_tokens > 0
    assert r.usage.completion_tokens > 0


async def test_gemini_streaming_usage(gemini_server):
    provider = GeminiProvider(api_key="dummy")
    provider.base_url = f"{gemini_server}/v1beta/models"

    responses = await _collect(provider, _request(stream=True))

    final_chunks = [r for r in responses if r.is_final]
    text_chunks = [r for r in responses if not r.is_final]

    assert len(final_chunks) == 1
    assert final_chunks[0].usage.completion_tokens > 0
    assert text_chunks[0].usage.prompt_tokens > 0


# ─── Ollama ────────────────────────────────────────────────────────────────

async def test_ollama_non_streaming_usage(ollama_server):
    provider = OllamaProvider(base_url=ollama_server)

    responses = await _collect(provider, _request(stream=False))

    assert len(responses) == 1
    r = responses[0]
    assert r.is_final is True
    assert r.usage.prompt_tokens > 0
    assert r.usage.completion_tokens > 0


async def test_ollama_streaming_usage(ollama_server):
    provider = OllamaProvider(base_url=ollama_server)

    responses = await _collect(provider, _request(stream=True))

    final_chunks = [r for r in responses if r.is_final]
    text_chunks = [r for r in responses if not r.is_final]

    assert len(final_chunks) == 1
    assert final_chunks[0].usage.completion_tokens > 0
    assert text_chunks[0].usage.prompt_tokens > 0


# ─── Streaming errors raise instead of yielding a fake chunk ──────────────

async def test_openai_streaming_error_raises(failing_openai_server):
    from fastapi import HTTPException
    provider = OpenAIProvider(api_key="dummy")
    provider._base_url = failing_openai_server

    with pytest.raises(HTTPException) as exc_info:
        await _collect(provider, _request(stream=True))
    assert exc_info.value.status_code == 500


async def test_anthropic_streaming_error_raises(failing_anthropic_server):
    from fastapi import HTTPException
    provider = AnthropicProvider(api_key="dummy")
    provider._base_url = failing_anthropic_server

    with pytest.raises(HTTPException) as exc_info:
        await _collect(provider, _request(stream=True))
    assert exc_info.value.status_code == 500


async def test_gemini_streaming_error_raises(failing_gemini_server):
    from fastapi import HTTPException
    provider = GeminiProvider(api_key="dummy")
    provider.base_url = f"{failing_gemini_server}/v1beta/models"

    with pytest.raises(HTTPException) as exc_info:
        await _collect(provider, _request(stream=True))
    assert exc_info.value.status_code == 500


async def test_ollama_streaming_error_raises(failing_ollama_server):
    from fastapi import HTTPException
    provider = OllamaProvider(base_url=failing_ollama_server)

    with pytest.raises(HTTPException) as exc_info:
        await _collect(provider, _request(stream=True))
    assert exc_info.value.status_code == 500
