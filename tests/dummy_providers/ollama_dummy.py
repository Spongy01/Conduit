from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

DUMMY_TOKENS = ["This ", "is ", "a ", "dummy ", "response."]


async def _stream(model: str):
    for token in DUMMY_TOKENS:
        yield json.dumps({"model": model, "message": {"role": "assistant", "content": token}, "done": False}) + "\n"
        await asyncio.sleep(0.01)
    yield json.dumps({"model": model, "message": {"role": "assistant", "content": ""}, "done": True}) + "\n"


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    model = body.get("model", "dummy-model")

    if body.get("stream", False):
        return StreamingResponse(_stream(model), media_type="application/x-ndjson")

    return {
        "model": model,
        "message": {"role": "assistant", "content": "This is a dummy response."},
        "done": True,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004)
