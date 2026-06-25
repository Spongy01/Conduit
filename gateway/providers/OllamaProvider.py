from base import BaseProvider
from schema import ChatCompletionRequest, ChatCompletionResponse
from typing import AsyncGenerator
import httpx
import json

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

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:

                if response.status_code != 200:
                    text = await response.aread()
                    raise Exception(f"Ollama API error {response.status_code}: {text}")

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

                    yield ChatCompletionResponse(model=model, full_response=content)
