from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

DUMMY_TOKENS = ["This ", "is ", "a ", "dummy ", "response."]
DUMMY_RESPONSE_TEXT = "".join(DUMMY_TOKENS)


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _prompt_tokens(body: dict) -> int:
    text = " ".join(m.get("content", "") for m in body.get("messages", []))
    return _estimate_tokens(text)


async def _stream_with_usage(model: str, body: dict, include_usage: bool):
    for token in DUMMY_TOKENS:
        chunk = {
            "id": "chatcmpl-dummy",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.01)

    if include_usage:
        prompt_tokens = _prompt_tokens(body)
        completion_tokens = _estimate_tokens(DUMMY_RESPONSE_TEXT)
        usage_chunk = {
            "id": "chatcmpl-dummy",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        yield f"data: {json.dumps(usage_chunk)}\n\n"

    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "dummy-model")

    if body.get("stream", False):
        include_usage = body.get("stream_options", {}).get("include_usage", False)
        return StreamingResponse(_stream_with_usage(model, body, include_usage), media_type="text/event-stream")

    prompt_tokens = _prompt_tokens(body)
    completion_tokens = _estimate_tokens(DUMMY_RESPONSE_TEXT)
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
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


if __name__ == "__main__":
    import uvicorn
    print("Starting OpenAI dummy server...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
