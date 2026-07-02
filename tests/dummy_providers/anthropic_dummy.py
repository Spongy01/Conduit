from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

DUMMY_TOKENS = ["This ", "is ", "a ", "dummy ", "response."]
DUMMY_RESPONSE_TEXT = "".join(DUMMY_TOKENS)


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _input_tokens(body: dict) -> int:
    text = " ".join(m.get("content", "") for m in body.get("messages", []))
    if body.get("system"):
        text = body["system"] + " " + text
    return _estimate_tokens(text)


async def _stream(model: str, body: dict):
    input_tokens = _input_tokens(body)
    output_tokens = _estimate_tokens(DUMMY_RESPONSE_TEXT)

    yield (
        f"event: message_start\n"
        f"data: {json.dumps({'type': 'message_start', 'message': {'id': 'msg-dummy', 'type': 'message', 'role': 'assistant', 'model': model, 'content': [], 'stop_reason': None, 'usage': {'input_tokens': input_tokens, 'output_tokens': 0}}})}\n\n"
    )
    yield (
        f"event: content_block_start\n"
        f"data: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
    )
    for token in DUMMY_TOKENS:
        chunk = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": token}}
        yield f"event: content_block_delta\ndata: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.01)
    yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
    yield (
        f"event: message_delta\n"
        f"data: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': output_tokens}})}\n\n"
    )
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop', 'stop_reason': 'end_turn'})}\n\n"


@app.post("/v1/messages")
async def messages(request: Request):
    body = await request.json()
    model = body.get("model", "dummy-model")

    if body.get("stream", False):
        return StreamingResponse(_stream(model, body), media_type="text/event-stream")

    input_tokens = _input_tokens(body)
    output_tokens = _estimate_tokens(DUMMY_RESPONSE_TEXT)
    return {
        "id": "msg-dummy",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "This is a dummy response."}],
        "model": model,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
