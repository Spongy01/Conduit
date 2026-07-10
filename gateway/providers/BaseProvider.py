"""Common interface every upstream LLM provider (OpenAI, Anthropic, Gemini,
Ollama) implements, so router.py and api/chat.py can treat them interchangeably."""
import asyncio
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
import httpx
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse

class BaseProvider(ABC):
    """Abstract base class for all LLM providers. Also holds the shared
    httpx.AsyncClient machinery every concrete provider uses to call its
    upstream API, so connection pooling/reuse is handled once here."""

    _client: Optional[httpx.AsyncClient] = None
    _client_loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Returns a long-lived AsyncClient reused across requests (so
        connections stay warm instead of being torn down and reopened every
        call). A client's connections are tied to the event loop they were
        opened on, so this rebuilds the client if the running loop has
        changed since it was created -- normally never, since a real
        process has exactly one loop for its whole lifetime, but this
        happens routinely in tests, which get a fresh loop per test
        function while PROVIDERS (and thus this client) is a process-wide
        singleton reused across the whole test session."""
        loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not loop:
            self._client = httpx.AsyncClient(timeout=None)
            self._client_loop = loop
        return self._client

    async def aclose(self):
        """Closes the shared connection pool, if one was ever created.
        Called on app shutdown."""
        if self._client is not None:
            await self._client.aclose()

    @abstractmethod
    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        """
        Generate a response based on the given request.
        This method should be implemented by subclasses to provide the actual response generation logic.
        This extracts the ChatCompletionRequest, and if required converts it to a format suitable for the specific provider, sends an API request,
        and then accepts yielded responses from the API or full response and convertes to ChatCompletionResponse format yields ChatCompletionResponse objects as they are generated.
        """
        pass
