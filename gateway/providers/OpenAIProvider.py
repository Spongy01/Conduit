from gateway.providers.BaseProvider import BaseProvider
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse, Usage
from gateway.core.tokens import estimate_tokens
from typing import AsyncGenerator
from fastapi import HTTPException
import httpx
import json
import logging
import os

logger = logging.getLogger(__name__)

class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")

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
        if stream:
            payload["stream_options"] = {"include_usage": True}

        input_text = " ".join(m.content for m in messages)
        input_token_estimate = estimate_tokens(input_text)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.debug("Calling OpenAI API model=%s stream=%s", model, stream)

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as response:

                if response.status_code != 200 and request.stream is False:
                    text = await response.aread()
                    logger.error("OpenAI API error status=%s model=%s: %s", response.status_code, model, text)
                    raise HTTPException(status_code=response.status_code, detail=f"OpenAI API error: {text}")
                if response.status_code != 200 and request.stream is True:
                    text = await response.aread()
                    logger.error("OpenAI API error status=%s model=%s: %s", response.status_code, model, text)
                    yield ChatCompletionResponse(model=model, delta=f"OpenAI API error: {text}")
                # =========================
                # STREAMING MODE
                # =========================
                if stream:
                    first_chunk = True
                    async for line in response.aiter_lines():

                        if not line.startswith("data:"):
                            continue

                        data = line[len("data:"):].strip()

                        if data == "[DONE]":
                            break

                        chunk = json.loads(data)

                        # Final usage-only chunk (empty choices), sent because we
                        # requested stream_options.include_usage.
                        if not chunk.get("choices") and "usage" in chunk:
                            usage = chunk["usage"]
                            yield ChatCompletionResponse(
                                model=model,
                                is_final=True,
                                usage=Usage(
                                    prompt_tokens=usage["prompt_tokens"],
                                    completion_tokens=usage["completion_tokens"],
                                    total_tokens=usage["total_tokens"],
                                ),
                            )
                            continue

                        delta = chunk["choices"][0].get("delta", {})

                        if "content" in delta:
                            content = delta["content"]
                            output_token_estimate = estimate_tokens(content)
                            yield ChatCompletionResponse(
                                model=model,
                                delta=content,
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
                        full["choices"][0]
                        ["message"]["content"]
                    )
                    usage = full["usage"]

                    logger.debug("OpenAI API response received model=%s", model)
                    yield ChatCompletionResponse(
                        model=model,
                        full_response=content,
                        is_final=True,
                        usage=Usage(
                            prompt_tokens=usage["prompt_tokens"],
                            completion_tokens=usage["completion_tokens"],
                            total_tokens=usage["total_tokens"],
                        ),
                    )