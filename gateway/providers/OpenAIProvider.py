from gateway.providers.BaseProvider import BaseProvider
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse
from typing import AsyncGenerator
from fastapi import HTTPException
import httpx
import json

class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        """
        Generate a response using the OpenAI API based on the given request.
        This method implements the actual response generation logic specific to the OpenAI provider.
        It extracts the ChatCompletionRequest, converts it to a format suitable for the OpenAI API, sends an API request,
        and then yields ChatCompletionResponse objects as they are generated.
        """
        # Implementation for generating responses using OpenAI API goes here
        
        model = request.model
        messages = request.messages
        stream = request.stream or False
        temperature = request.temperature if request.temperature is not None else 0.7
        max_tokens = request.max_tokens if request.max_tokens is not None else 200

        payload = {
            "model": model,
            "messages": [m.dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as response:

                if response.status_code != 200 and request.stream is False:
                    text = await response.aread()
                    raise HTTPException(status_code=response.status_code, detail=f"OpenAI API error: {text}")
                if response.status_code != 200 and request.stream is True:
                    text = await response.aread()
                    yield ChatCompletionResponse(model=model, delta=f"OpenAI API error: {text}")
                # =========================
                # STREAMING MODE
                # =========================
                if stream:
                    async for line in response.aiter_lines():

                        if not line.startswith("data:"):
                            continue

                        data = line[len("data:"):].strip()

                        if data == "[DONE]":
                            break

                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})

                        if "content" in delta:
                            yield ChatCompletionResponse(
                                model=model,
                                delta=delta["content"]
                            )

                # =========================
                # NON-STREAMING MODE
                # =========================
                else:
                    data = await response.aread()
                    full = json.loads(data)

                    content = (
                        full["choices"][0]
                        ["message"]["content"]
                    )

                    yield ChatCompletionResponse(
                        model=model,
                        full_response=content
                    )