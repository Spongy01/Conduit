"""Request size limits that stop a public caller from sending prompts big
enough to tie up the (laptop-hosted) model backends.

Limits are read from the environment on every use, so they can be changed
without reloading modules (and tests can override them). An unset, invalid
or non-positive value falls back to the default rather than crashing or,
worse, silently disabling the limit."""
import logging
import os

from fastapi import HTTPException
from starlette.responses import JSONResponse

from gateway.core.schema import ChatCompletionRequest

logger = logging.getLogger(__name__)

DEFAULTS = {
    "MAX_REQUEST_BYTES": 1_000_000,
    "MAX_PROMPT_CHARS": 100_000,
    "MAX_MESSAGES": 200,
    "MAX_OUTPUT_TOKENS": 4096,
}

_BODY_METHODS = {"POST", "PUT", "PATCH"}


def get_limit(name: str) -> int:
    """Returns the positive integer limit for `name`, or its default if the
    env var is unset, not an integer, or <= 0 (warning in the latter two)."""
    default = DEFAULTS[name]
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError("must be positive")
    except ValueError:
        logger.warning("Invalid %s=%r (expected a positive integer); using default %d", name, raw, default)
        return default
    return value


def raise_if_chat_too_large(request: ChatCompletionRequest) -> None:
    """Raises 413 if the request has too many messages or too many total
    characters of message content. Cheap checks only; run after auth and
    model access, but before rate limiting and budget reservation, so a
    rejected request costs the team nothing."""
    max_messages = get_limit("MAX_MESSAGES")
    if len(request.messages) > max_messages:
        raise HTTPException(status_code=413,
                            detail=f"Too many messages: {len(request.messages)} (limit {max_messages})")

    max_chars = get_limit("MAX_PROMPT_CHARS")
    total_chars = sum(len(m.content) for m in request.messages)
    if total_chars > max_chars:
        raise HTTPException(status_code=413,
                            detail=f"Prompt too large: {total_chars} characters (limit {max_chars})")


def apply_output_ceiling(request: ChatCompletionRequest) -> None:
    """Clamps a caller-supplied max_tokens down to MAX_OUTPUT_TOKENS. An unset
    max_tokens is left alone here: paid providers apply their own small
    default, and the Ollama provider applies this same ceiling itself (so a
    local model can't be asked to generate without end). Clamping, not
    rejecting, keeps well-meaning clients working."""
    ceiling = get_limit("MAX_OUTPUT_TOKENS")
    if request.max_tokens is not None and request.max_tokens > ceiling:
        request.max_tokens = ceiling


class RequestBodyLimitMiddleware:
    """Pure ASGI middleware rejecting oversized POST/PUT/PATCH bodies with
    413 before anything is parsed and before auth, rate limiting or budget
    work. Checks Content-Length up front; bodies without one (chunked) are
    counted as they stream in, aborting once the limit is crossed."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        limit = get_limit("MAX_REQUEST_BYTES")
        too_large = JSONResponse(status_code=413,
                                 content={"detail": f"Request body too large (limit {limit} bytes)"})

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await too_large(scope, receive, send)
                    return
            except ValueError:
                pass  # malformed header: let the server/app deal with it; streamed count still applies

        received = 0
        response_started = False
        rejected = False

        async def counting_receive():
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request" and not rejected:
                received += len(message.get("body", b""))
                if received > limit and not response_started:
                    # Answer 413 right here rather than raising: FastAPI's body
                    # reader turns any exception from receive() into a 400. We
                    # then report a disconnect so the app stops reading, and
                    # drop whatever the app tries to send afterwards.
                    rejected = True
                    await too_large(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def tracking_send(message):
            nonlocal response_started
            if rejected:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except Exception:
            if not rejected:
                raise
            # The app failed only because we cut its body off; 413 already sent.
