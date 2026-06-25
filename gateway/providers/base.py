from abc import ABC, abstractmethod
from typing import AsyncGenerator
from schema import ChatCompletionRequest, ChatCompletionResponse

class BaseProvider(ABC):
    
    @abstractmethod
    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        """
        Generate a response based on the given request.
        This method should be implemented by subclasses to provide the actual response generation logic.
        This extracts the ChatCompletionRequest, and if required converts it to a format suitable for the specific provider, sends an API request,
        and then accepts yielded responses from the API or full response and convertes to ChatCompletionResponse format yields ChatCompletionResponse objects as they are generated.
        """
        pass
