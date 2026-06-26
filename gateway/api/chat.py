from fastapi import APIRouter
from gateway.core.schema import ChatCompletionRequest
from gateway.providers.BaseProvider import BaseProvider
from gateway.providers.OpenAIProvider import OpenAIProvider
from fastapi.responses import StreamingResponse
from fastapi import HTTPException
router = APIRouter()

async def return_streaming_response(request: ChatCompletionRequest, provider: BaseProvider):
    """
    Handle streaming response for chat completion requests.
    This function processes the request and yields responses as they are generated.
    """
    
    async for response in provider.generate(request):
        yield "data: " + response.model_dump_json() + "\n\n"


@router.post("/v1/chat/completion")
async def chat_completion(request: ChatCompletionRequest):
    """
    Endpoint to handle chat completion requests.
    This endpoint receives a ChatCompletionRequest, processes it, and returns the generated response.
    """

    # Skeletal implementation for handling the chat completion request.
    #Call OpenAIProvider for chat_completion and return the response.
    stream = request.stream or False
    provider = OpenAIProvider(api_key="YOUR_API_KEY")

    if stream:
        return StreamingResponse(return_streaming_response(request, provider))
    
    # Non-streaming mode: Call OpenAIProvider for chat_completion and return the response.
    response_list = []
    async for response in provider.generate(request):
        response_list.append(response.model_dump())
    
    if len(response_list) == 0:
        raise HTTPException(status_code=500, detail="No response generated.")
    if len(response_list) == 1:
        return response_list[0]
    
    # should not have more than 1 response in non-streaming mode, but if it does, return error
    raise HTTPException(status_code=500, detail="Multiple responses generated in non-streaming mode.")