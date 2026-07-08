"""Chat completion API: authenticates the caller, enforces model access,
rate limits, and budget, then routes the request to a provider (with
automatic fallback) and streams or returns its response."""
import logging
import math
import time
from fastapi import APIRouter, Depends
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from gateway.auth.authenticate import authenticate
from gateway.policy.model_access import raise_if_model_not_allowed
from gateway.policy.rate_limiter import check_rate_limit
from gateway.policy.budget import settle_budget
from gateway.router.router import route_request, NoProviderAvailableError
from gateway.core import metrics
from gateway.core.database import db
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

router = APIRouter()


def _provider_for_model(team: dict, model_name: str) -> str:
    """Looks up which provider serves `model_name` in the team's enriched
    allowed_models, for use as a metric label before routing (and any
    fallback) has resolved an actual provider. Falls back to "unknown" if
    the model isn't in the team's allowed list (e.g. a 403 is imminent)."""
    for m in team.get("allowed_models", []):
        if m["name"] == model_name:
            return m["provider"]
    return "unknown"


async def _settle_quietly(api_key: str, model: str, team: dict, reservation_id: str,
                           input_tokens: int, output_tokens: int):
    """Best-effort settle: a settlement failure shouldn't take down a response
    that's already been produced (or, for streaming, already sent to the client).
    On success, also refreshes the team's budget_utilization gauge from the
    team's actual post-settlement spend."""
    try:
        await settle_budget(api_key, model, team, reservation_id, input_tokens, output_tokens)
    except ValueError as e:
        logger.warning("Failed to settle budget reservation_id=%s: %s", reservation_id, e)
        return

    budget_limit = team.get("budget_limit")
    if not budget_limit:
        return
    fresh_team = await db.get_team(api_key)
    if fresh_team is None:
        return
    metrics.budget_utilization.labels(team_id=team.get("team_id")).set(
        float(fresh_team["current_spend"]) / float(budget_limit)
    )


async def return_streaming_response(generator: AsyncGenerator[ChatCompletionResponse, None],
                                     team: dict, reservation_id: str, requested_model: str):
    """
    Streams the router's winning generator to the client, settling budget
    against whichever model actually served the request once the stream
    ends.
    """
    final_usage = None
    actual_model = requested_model
    async for response in generator:
        actual_model = response.model
        if response.is_final and response.usage is not None:
            final_usage = response.usage
        yield "data: " + response.model_dump_json() + "\n\n"

    if actual_model != requested_model:
        logger.info("Fallback served team_id=%s requested_model=%s actual_model=%s",
                    team.get("team_id"), requested_model, actual_model)

    if final_usage is not None:
        await _settle_quietly(team["api_key"], actual_model, team, reservation_id,
                               final_usage.prompt_tokens, final_usage.completion_tokens)
    else:
        await _settle_quietly(team["api_key"], actual_model, team, reservation_id, 0, 0)


async def _stream_with_metrics(generator, team, reservation_id, requested_model, provider, metric_labels, start_time):
    """Wraps return_streaming_response to additionally record
    time_to_first_token_seconds (on the first chunk yielded) and, once the
    stream is fully drained, the inflight/duration/requests_total metrics
    that — for a streaming response — can only be known after the last
    chunk is sent (chat_completion itself returns long before that
    happens, since Starlette drains a StreamingResponse's generator after
    the endpoint function has already returned)."""
    first_chunk_at = None
    status = "success"
    try:
        async for chunk in return_streaming_response(generator, team, reservation_id, requested_model):
            if first_chunk_at is None:
                first_chunk_at = time.monotonic()
                metrics.time_to_first_token_seconds.labels(provider=provider, model=requested_model).observe(
                    first_chunk_at - start_time
                )
            yield chunk
    except Exception:
        status = "error"
        raise
    finally:
        duration = time.monotonic() - start_time
        metrics.inflight_requests.labels(**metric_labels).dec()
        metrics.request_duration_seconds.labels(status=status, **metric_labels).observe(duration)
        metrics.requests_total.labels(status=status, **metric_labels).inc()


@router.post("/v1/chat/completion")
async def chat_completion(request: ChatCompletionRequest,
                          team: dict = Depends(authenticate)):
    """
    Endpoint to handle chat completion requests.
    This endpoint receives a ChatCompletionRequest, processes it, and returns the generated response.
    """
    team_id = team.get("team_id")
    logger.debug("Chat completion request team_id=%s model=%s stream=%s", team_id, request.model, request.stream)

    provider = _provider_for_model(team, request.model)
    metric_labels = {"team_id": team_id, "provider": provider, "model": request.model}
    stream = request.stream
    start_time = time.monotonic()
    metrics.inflight_requests.labels(**metric_labels).inc()
    status = "success"
    streaming_started = False

    try:
        # Check if the requested model is allowed for the team
        raise_if_model_not_allowed(request, team)

        ##############
        # Rate limiting logic
        ##############
        team["rate_limit"] = float(team["rate_limit"])
        team["budget_limit"] = float(team["budget_limit"])
        # model is allowed, check rate limiter
        # Token bucket: capacity is requests/minute, fill_rate converts that to
        # tokens refilled per second so the bucket refills continuously.
        allowed = await check_rate_limit(
            team_id=team["team_id"],
            capacity=team["rate_limit"],
            fill_rate=team["rate_limit"] / 60.0,
            model=request.model)

        logger.debug("Rate limit result team_id=%s allowed=%s", team_id, allowed)

        if not allowed:
            # Worst case wait for one token to refill, rounded up for the client.
            retry_after = math.ceil(60.0 / team["rate_limit"])
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.",
                                headers={"Retry-After": str(retry_after)})

        ##############
        # Routing (reserves budget per attempt and falls back on retryable failures)
        ##############
        try:
            generator, reservation_id = await route_request(request, team)
        except NoProviderAvailableError as e:
            logger.error("No provider available team_id=%s model=%s: %s", team_id, request.model, e)
            raise HTTPException(status_code=503, detail=str(e))
        except ValueError as e:
            logger.warning("Budget reservation denied team_id=%s model=%s: %s", team_id, request.model, e)
            raise HTTPException(status_code=402, detail=str(e))

        logger.debug("Routed team_id=%s requested_model=%s", team_id, request.model)

        # Streaming mode: Return a streaming response if requested. inflight/
        # duration/requests_total finish inside _stream_with_metrics once the
        # stream is fully drained, not here (see design note above).
        if stream:
            streaming_started = True
            return StreamingResponse(
                _stream_with_metrics(generator, team, reservation_id, request.model, provider, metric_labels, start_time)
            )

        # Non-streaming mode: Call the provider for chat_completion and return the response.
        response_list = []
        try:
            async for response in generator:
                response_list.append(response)
        except HTTPException:
            await _settle_quietly(team["api_key"], request.model, team, reservation_id, 0, 0)
            raise

        logger.debug("Provider response received team_id=%s model=%s response_count=%d", team_id, request.model, len(response_list))

        if len(response_list) == 0:
            logger.error("No response generated team_id=%s model=%s", team_id, request.model)
            await _settle_quietly(team["api_key"], request.model, team, reservation_id, 0, 0)
            raise HTTPException(status_code=500, detail="No response generated.")
        if len(response_list) == 1:
            response = response_list[0]
            actual_model = response.model
            if actual_model != request.model:
                logger.info("Fallback served team_id=%s requested_model=%s actual_model=%s",
                            team_id, request.model, actual_model)
            if response.usage is not None:
                await _settle_quietly(team["api_key"], actual_model, team, reservation_id,
                                       response.usage.prompt_tokens, response.usage.completion_tokens)
            else:
                await _settle_quietly(team["api_key"], actual_model, team, reservation_id, 0, 0)
            return response.model_dump()

        # should not have more than 1 response in non-streaming mode, but if it does, return error
        logger.error("Multiple responses generated in non-streaming mode team_id=%s model=%s", team_id, request.model)
        await _settle_quietly(team["api_key"], request.model, team, reservation_id, 0, 0)
        raise HTTPException(status_code=500, detail="Multiple responses generated in non-streaming mode.")

    except HTTPException as e:
        status = f"http_{e.status_code}"
        raise
    except Exception:
        status = "error"
        raise
    finally:
        if not streaming_started:
            duration = time.monotonic() - start_time
            metrics.inflight_requests.labels(**metric_labels).dec()
            metrics.request_duration_seconds.labels(status=status, **metric_labels).observe(duration)
            metrics.requests_total.labels(status=status, **metric_labels).inc()
