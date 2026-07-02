from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

DUMMY_TOKENS = ["This ", "is ", "a ", "dummy ", "response."]
DUMMY_RESPONSE_TEXT = "".join(DUMMY_TOKENS)


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _prompt_eval_count(body: dict) -> int:
    text = " ".join(m.get("content", "") for m in body.get("messages", []))
    return _estimate_tokens(text)


async def _stream(model: str, body: dict):
    for token in DUMMY_TOKENS:
        yield json.dumps({"model": model, "message": {"role": "assistant", "content": token}, "done": False}) + "\n"
        await asyncio.sleep(0.01)

    yield json.dumps({
        "model": model,
        "message": {"role": "assistant", "content": ""},
        "done": True,
        "prompt_eval_count": _prompt_eval_count(body),
        "eval_count": _estimate_tokens(DUMMY_RESPONSE_TEXT),
    }) + "\n"


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    model = body.get("model", "dummy-model")

    if body.get("stream", False):
        return StreamingResponse(_stream(model, body), media_type="application/x-ndjson")

    return {
        "model": model,
        "message": {"role": "assistant", "content": "This is a dummy response."},
        "done": True,
        "prompt_eval_count": _prompt_eval_count(body),
        "eval_count": _estimate_tokens(DUMMY_RESPONSE_TEXT),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
