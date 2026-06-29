from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

DUMMY_TOKENS = ["This ", "is ", "a ", "dummy ", "response."]


async def _stream(model: str):
    for token in DUMMY_TOKENS:
        chunk = {
            "id": "chatcmpl-dummy",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.01)
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "dummy-model")

    if body.get("stream", False):
        return StreamingResponse(_stream(model), media_type="text/event-stream")

    return {
        "id": "chatcmpl-dummy",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "This is a dummy response."},
                "finish_reason": "stop",
            }
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
