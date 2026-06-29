from gateway.providers.BaseProvider import BaseProvider
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse
from typing import AsyncGenerator
import httpx
import json
import os
from fastapi import HTTPException

class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        model = request.model
        stream = request.stream or False
        temperature = request.temperature if request.temperature is not None else 0.7
        max_tokens = request.max_tokens if request.max_tokens is not None else 200

        # Anthropic separates system messages into a top-level "system" field;
        # only "user" and "assistant" roles are allowed in "messages".
        system_parts = []
        messages = []
        for m in request.messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/messages",
                headers=headers,
                json=payload,
            ) as response:

                if response.status_code != 200 and request.stream is False:
                    text = await response.aread()
                    raise HTTPException(status_code=response.status_code, detail=f"Anthropic API error: {text}")
                if response.status_code != 200 and request.stream is True:
                    text = await response.aread()
                    yield ChatCompletionResponse(model=model, delta=f"Anthropic API error: {text}")
                # =========================
                # STREAMING MODE
                # =========================
                if stream:
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue

                        data = line[len("data:"):].strip()
                        chunk = json.loads(data)

                        # Only content_block_delta events carry text
                        if chunk.get("type") == "content_block_delta":
                            delta = chunk.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                if text:
                                    yield ChatCompletionResponse(model=model, delta=text)

                # =========================
                # NON-STREAMING MODE
                # =========================
                else:
                    data = await response.aread()
                    full = json.loads(data)

                    content = full["content"][0]["text"]

                    yield ChatCompletionResponse(model=model, full_response=content)
