from fastAPI import APIRouter
from schema import ChatCompletionRequest
from providers import OpenAIProvider, BaseProvider
from fastapi.responses import StreamingResponse
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
    async for response in provider.generate(request):
        return response
