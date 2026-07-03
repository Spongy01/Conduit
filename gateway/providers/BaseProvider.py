"""Common interface every upstream LLM provider (OpenAI, Anthropic, Gemini,
Ollama) implements, so router.py and api/chat.py can treat them interchangeably."""
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse

class BaseProvider(ABC):
    """Abstract base class for all LLM providers."""


    @abstractmethod
    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        """
        Generate a response based on the given request.
        This method should be implemented by subclasses to provide the actual response generation logic.
        This extracts the ChatCompletionRequest, and if required converts it to a format suitable for the specific provider, sends an API request,
        and then accepts yielded responses from the API or full response and convertes to ChatCompletionResponse format yields ChatCompletionResponse objects as they are generated.
        """
        pass
