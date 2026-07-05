from gateway.providers.BaseProvider import BaseProvider
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse, Usage
from gateway.core.tokens import estimate_tokens
from typing import AsyncGenerator
import httpx
import json
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class OllamaProvider(BaseProvider):
    """BaseProvider implementation for a local/self-hosted Ollama server."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def generate(self, request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
        """Translates a ChatCompletionRequest into an Ollama /api/chat call
        and yields ChatCompletionResponse chunks (streaming) or a single
        final response (non-streaming). Ollama has no real cost (self-hosted),
        so usage here is only for budget/logging bookkeeping."""
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

        input_text = " ".join(m.content for m in request.messages)
        input_token_estimate = estimate_tokens(input_text)

        headers = {"Content-Type": "application/json"}
        url = f"{self.base_url}/api/chat"

        logger.debug("Calling Ollama API model=%s stream=%s", model, stream)

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:

                if response.status_code != 200:
                    text = await response.aread()
                    logger.error("Ollama API error status=%s model=%s: %s", response.status_code, model, text)
                    raise HTTPException(status_code=response.status_code, detail=f"Ollama API error: {text}")
                # =========================
                # STREAMING MODE
                # =========================
                if stream:
                    first_chunk = True
                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")

                        if content:
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

                        if chunk.get("done"):
                            prompt_eval_count = chunk.get("prompt_eval_count", input_token_estimate)
                            eval_count = chunk.get("eval_count", 0)
                            yield ChatCompletionResponse(
                                model=model,
                                is_final=True,
                                usage=Usage(
                                    prompt_tokens=prompt_eval_count,
                                    completion_tokens=eval_count,
                                    total_tokens=prompt_eval_count + eval_count,
                                ),
                            )
                            break

                # =========================
                # NON-STREAMING MODE
                # =========================
                else:
                    data = await response.aread()
                    full = json.loads(data)

                    content = full["message"]["content"]
                    prompt_eval_count = full.get("prompt_eval_count", input_token_estimate)
                    eval_count = full.get("eval_count", 0)

                    logger.debug("Ollama API response received model=%s", model)
                    yield ChatCompletionResponse(
                        model=model,
                        full_response=content,
                        is_final=True,
                        usage=Usage(
                            prompt_tokens=prompt_eval_count,
                            completion_tokens=eval_count,
                            total_tokens=prompt_eval_count + eval_count,
                        ),
                    )
