from gateway.providers.BaseProvider import BaseProvider
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse, Usage
from gateway.core.tokens import estimate_tokens
from gateway.core.tracer import tracer
from typing import AsyncGenerator
import httpx
import json
import logging
import os
import sys
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class AnthropicProvider(BaseProvider):
    """BaseProvider implementation for the Anthropic Messages API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        self._client = httpx.AsyncClient(timeout=None)

    async def aclose(self):
        """Closes the shared connection pool. Called on app shutdown."""
        await self._client.aclose()

    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        """Translates a ChatCompletionRequest into an Anthropic /v1/messages
        call and yields ChatCompletionResponse chunks (streaming) or a single
        final response (non-streaming), each carrying token usage."""
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

        input_text = " ".join(system_parts) + " " + " ".join(m.content for m in request.messages)
        input_token_estimate = estimate_tokens(input_text)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        logger.debug("Calling Anthropic API model=%s stream=%s", model, stream)

        stream_cm = self._client.stream(
            "POST",
            f"{self._base_url}/v1/messages",
            headers=headers,
            json=payload,
        )
        with tracer.start_as_current_span("conduit.anthropic.httpx_connection"):
            response = await stream_cm.__aenter__()
        try:
            if response.status_code != 200:
                text = await response.aread()
                logger.error("Anthropic API error status=%s model=%s: %s", response.status_code, model, text)
                raise HTTPException(status_code=response.status_code, detail=f"Anthropic API error: {text}")
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

                    # Only content_block_delta events carry text
                    if chunk.get("type") == "content_block_delta":
                        delta = chunk.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
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

                    # message_delta carries the final, actual output token count
                    elif chunk.get("type") == "message_delta":
                        usage = chunk.get("usage", {})
                        if "output_tokens" in usage:
                            yield ChatCompletionResponse(
                                model=model,
                                is_final=True,
                                usage=Usage(
                                    prompt_tokens=input_token_estimate,
                                    completion_tokens=usage["output_tokens"],
                                    total_tokens=input_token_estimate + usage["output_tokens"],
                                ),
                            )

            # =========================
            # NON-STREAMING MODE
            # =========================
            else:
                data = await response.aread()
                full = json.loads(data)

                content = full["content"][0]["text"]
                usage = full["usage"]

                logger.debug("Anthropic API response received model=%s", model)
                yield ChatCompletionResponse(
                    model=model,
                    full_response=content,
                    is_final=True,
                    usage=Usage(
                        prompt_tokens=usage["input_tokens"],
                        completion_tokens=usage["output_tokens"],
                        total_tokens=usage["input_tokens"] + usage["output_tokens"],
                    ),
                )
        finally:
            await stream_cm.__aexit__(*sys.exc_info())
