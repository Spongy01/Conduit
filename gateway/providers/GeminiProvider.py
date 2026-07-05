from gateway.providers.BaseProvider import BaseProvider
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse, Usage
from gateway.core.tokens import estimate_tokens
from typing import AsyncGenerator
import httpx
import json
import logging
import os
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class GeminiProvider(BaseProvider):
    """BaseProvider implementation for the Google Gemini generateContent API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        _base = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
        self.base_url = f"{_base}/v1beta/models"

    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        """Translates a ChatCompletionRequest into a Gemini generateContent/
        streamGenerateContent call and yields ChatCompletionResponse chunks
        (streaming) or a single final response (non-streaming)."""
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

        input_text = " ".join(p["text"] for p in system_parts) + " " + " ".join(m.content for m in request.messages)
        input_token_estimate = estimate_tokens(input_text)

        headers = {"Content-Type": "application/json"}

        if stream:
            url = f"{self.base_url}/{model}:streamGenerateContent?alt=sse&key={self.api_key}"
        else:
            url = f"{self.base_url}/{model}:generateContent?key={self.api_key}"

        logger.debug("Calling Gemini API model=%s stream=%s", model, stream)

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:

                if response.status_code != 200:
                    text = await response.aread()
                    logger.error("Gemini API error status=%s model=%s: %s", response.status_code, model, text)
                    raise HTTPException(status_code=response.status_code, detail=f"Gemini API error: {text}")
                # =========================
                # STREAMING MODE
                # =========================
                if stream:
                    first_chunk = True
                    async for line in response.aiter_lines():

                        if not line.startswith("data:"):
                            continue

                        data = line[len("data:"):].strip()

                        chunk = json.loads(data)
                        candidates = chunk.get("candidates", [])

                        # Final chunk: no text, carries the actual usage totals.
                        if chunk.get("usageMetadata") and (
                            not candidates or candidates[0].get("finishReason")
                        ):
                            usage = chunk["usageMetadata"]
                            yield ChatCompletionResponse(
                                model=model,
                                is_final=True,
                                usage=Usage(
                                    prompt_tokens=usage["promptTokenCount"],
                                    completion_tokens=usage["candidatesTokenCount"],
                                    total_tokens=usage["totalTokenCount"],
                                ),
                            )
                            continue

                        if not candidates:
                            continue

                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            text = part.get("text", "")
                            if text:
                                output_token_estimate = estimate_tokens(text)
                                yield ChatCompletionResponse(
                                    model=model,
                                    delta=text,
                                    usage=Usage(
                                        prompt_tokens=input_token_estimate if first_chunk else 0,
                                        completion_tokens=output_token_estimate,
                                        total_tokens=(input_token_estimate if first_chunk else 0) + output_token_estimate,
                                    ),
                                )
                                first_chunk = False

                # =========================
                # NON-STREAMING MODE
                # =========================
                else:
                    data = await response.aread()
                    full = json.loads(data)

                    content = (
                        full["candidates"][0]["content"]["parts"][0]["text"]
                    )
                    usage = full["usageMetadata"]

                    logger.debug("Gemini API response received model=%s", model)
                    yield ChatCompletionResponse(
                        model=model,
                        full_response=content,
                        is_final=True,
                        usage=Usage(
                            prompt_tokens=usage["promptTokenCount"],
                            completion_tokens=usage["candidatesTokenCount"],
                            total_tokens=usage["totalTokenCount"],
                        ),
                    )
