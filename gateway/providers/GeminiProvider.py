from gateway.providers.BaseProvider import BaseProvider
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse
from typing import AsyncGenerator
import httpx
import json
import logging
import os
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        _base = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
        self.base_url = f"{_base}/v1beta/models"

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

        logger.debug("Calling Gemini API model=%s stream=%s", model, stream)

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:

                if response.status_code != 200 and request.stream is False:
                    text = await response.aread()
                    logger.error("Gemini API error status=%s model=%s: %s", response.status_code, model, text)
                    raise HTTPException(status_code=response.status_code, detail=f"Gemini API error: {text}")
                if response.status_code != 200 and request.stream is True:
                    text = await response.aread()
                    logger.error("Gemini API error status=%s model=%s: %s", response.status_code, model, text)
                    yield ChatCompletionResponse(model=model, delta=f"Gemini API error: {text}")
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

                    logger.debug("Gemini API response received model=%s", model)
                    yield ChatCompletionResponse(model=model, full_response=content)
