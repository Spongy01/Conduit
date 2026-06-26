from gateway.providers.BaseProvider import BaseProvider
from gateway.schema import ChatCompletionRequest, ChatCompletionResponse
from typing import AsyncGenerator
import httpx
import json

class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        model = request.model
        stream = request.stream or False
        temperature = request.temperature if request.temperature is not None else 0.7
        max_tokens = request.max_tokens if request.max_tokens is not None else 200

        # Gemini uses "model" role instead of "assistant", and system messages
        # are passed via a separate "systemInstruction" field.
        system_parts = []
        contents = []
        for m in request.messages:
            if m.role == "system":
                system_parts.append({"text": m.content})
            else:
                gemini_role = "model" if m.role == "assistant" else m.role
                contents.append({"role": gemini_role, "parts": [{"text": m.content}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        headers = {"Content-Type": "application/json"}

        if stream:
            url = f"{self.base_url}/{model}:streamGenerateContent?alt=sse&key={self.api_key}"
        else:
            url = f"{self.base_url}/{model}:generateContent?key={self.api_key}"

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:

                if response.status_code != 200:
                    text = await response.aread()
                    raise Exception(f"Gemini API error {response.status_code}: {text}")

                # =========================
                # STREAMING MODE
                # =========================
                if stream:
                    async for line in response.aiter_lines():

                        if not line.startswith("data:"):
                            continue

                        data = line[len("data:"):].strip()

                        chunk = json.loads(data)
                        candidates = chunk.get("candidates", [])
                        if not candidates:
                            continue

                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            text = part.get("text", "")
                            if text:
                                yield ChatCompletionResponse(model=model, delta=text)

                # =========================
                # NON-STREAMING MODE
                # =========================
                else:
                    data = await response.aread()
                    full = json.loads(data)

                    content = (
                        full["candidates"][0]["content"]["parts"][0]["text"]
                    )

                    yield ChatCompletionResponse(model=model, full_response=content)
