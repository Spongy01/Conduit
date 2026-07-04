"""Chat completion API: authenticates the caller, enforces model access,
rate limits, and budget, then routes the request to a provider (with
automatic fallback) and streams or returns its response."""
import logging
import math
from fastapi import APIRouter, Depends
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from gateway.auth.authenticate import authenticate
from gateway.policy.model_access import raise_if_model_not_allowed
from gateway.policy.rate_limiter import check_rate_limit
from gateway.policy.budget import settle_budget
from gateway.router.router import route_request, NoProviderAvailableError
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

router = APIRouter()

async def _settle_quietly(api_key: str, model: str, team: dict, reservation_id: str,
                           input_tokens: int, output_tokens: int):
    """Best-effort settle: a settlement failure shouldn't take down a response
    that's already been produced (or, for streaming, already sent to the client)."""
    try:
        await settle_budget(api_key, model, team, reservation_id, input_tokens, output_tokens)
    except ValueError as e:
        logger.warning("Failed to settle budget reservation_id=%s: %s", reservation_id, e)


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
        logger.info("Fallback served requested_model=%s actual_model=%s", requested_model, actual_model)

    if final_usage is not None:
        await _settle_quietly(team["api_key"], actual_model, team, reservation_id,
                               final_usage.prompt_tokens, final_usage.completion_tokens)
    else:
        await _settle_quietly(team["api_key"], actual_model, team, reservation_id, 0, 0)


@router.post("/v1/chat/completion")
async def chat_completion(request: ChatCompletionRequest,
                          team: dict = Depends(authenticate)):
    """
    Endpoint to handle chat completion requests.
    This endpoint receives a ChatCompletionRequest, processes it, and returns the generated response.
    """
    team_id = team.get("team_id")
    logger.debug("Chat completion request team_id=%s model=%s stream=%s", team_id, request.model, request.stream)

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
        fill_rate=team["rate_limit"] / 60.0)

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

    #streaming status
    stream = request.stream

    logger.debug("Routed team_id=%s requested_model=%s", team_id, request.model)

    # Streaming mode: Return a streaming response if requested.
    if stream:
        return StreamingResponse(return_streaming_response(generator, team, reservation_id, request.model))

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
