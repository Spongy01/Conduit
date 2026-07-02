from gateway.providers.BaseProvider import BaseProvider
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse
from typing import AsyncGenerator
import httpx
import json
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class OllamaProvider(BaseProvider):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        model = request.model
        stream = request.stream or False
        temperature = request.temperature if request.temperature is not None else 0.7
        max_tokens = request.max_tokens if request.max_tokens is not None else 200

        payload = {
            "model": model,
            "messages": [m.dict() for m in request.messages],
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/api/chat"

        logger.debug("Calling Ollama API model=%s stream=%s", model, stream)

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:

                if response.status_code != 200 and request.stream is False:
                    text = await response.aread()
                    logger.error("Ollama API error status=%s model=%s: %s", response.status_code, model, text)
                    raise HTTPException(status_code=response.status_code, detail=f"Ollama API error: {text}")
                if response.status_code != 200 and request.stream is True:
                    text = await response.aread()
                    logger.error("Ollama API error status=%s model=%s: %s", response.status_code, model, text)
                    yield ChatCompletionResponse(model=model, delta=f"Ollama API error: {text}")
                # =========================
                # STREAMING MODE
                # =========================
                if stream:
                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")

                        if content:
                            yield ChatCompletionResponse(model=model, delta=content)

                        if chunk.get("done"):
                            break

                # =========================
                # NON-STREAMING MODE
                # =========================
                else:
                    data = await response.aread()
                    full = json.loads(data)

                    content = full["message"]["content"]

                    logger.debug("Ollama API response received model=%s", model)
                    yield ChatCompletionResponse(model=model, full_response=content)
