import logging
import math
from fastapi import APIRouter, Depends
from gateway.core.schema import ChatCompletionRequest
from gateway.providers.BaseProvider import BaseProvider
from gateway.providers.OpenAIProvider import OpenAIProvider
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
from gateway.auth.authenticate import authenticate
from gateway.policy.model_access import raise_if_model_not_allowed
from gateway.policy.rate_limiter import check_rate_limit
from gateway.router.router import route_request

logger = logging.getLogger(__name__)

router = APIRouter()

async def return_streaming_response(request: ChatCompletionRequest, provider: BaseProvider):
    """
    Handle streaming response for chat completion requests.
    This function processes the request and yields responses as they are generated.
    """
    
    async for response in provider.generate(request):
        yield "data: " + response.model_dump_json() + "\n\n"


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
    team["rate_limit"] = float(team["rate_limit"])
    team["budget_limit"] = float(team["budget_limit"])
    # model is allowed, check rate limiter
    allowed = await check_rate_limit(
        team_id=team["team_id"],
        capacity=team["rate_limit"],
        fill_rate=team["rate_limit"] / 60.0)

    logger.debug("Rate limit result team_id=%s allowed=%s", team_id, allowed)

    if not allowed:
        retry_after = math.ceil(60.0 / team["rate_limit"])
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please try again later.",
                            headers={"Retry-After": str(retry_after)})


    # get provider from router
    provider = route_request(request, team)

    #streaming status
    stream = request.stream

    logger.debug("Calling provider=%s team_id=%s model=%s", type(provider).__name__, team_id, request.model)

    # Streaming mode: Return a streaming response if requested.
    if stream:
        return StreamingResponse(return_streaming_response(request, provider))

    # Non-streaming mode: Call the provider for chat_completion and return the response.
    response_list = []
    async for response in provider.generate(request):
        response_list.append(response.model_dump())

    logger.debug("Provider response received team_id=%s model=%s response_count=%d", team_id, request.model, len(response_list))

    if len(response_list) == 0:
        logger.error("No response generated team_id=%s model=%s", team_id, request.model)
        raise HTTPException(status_code=500, detail="No response generated.")
    if len(response_list) == 1:
        return response_list[0]

    # should not have more than 1 response in non-streaming mode, but if it does, return error
    logger.error("Multiple responses generated in non-streaming mode team_id=%s model=%s", team_id, request.model)
    raise HTTPException(status_code=500, detail="Multiple responses generated in non-streaming mode.")