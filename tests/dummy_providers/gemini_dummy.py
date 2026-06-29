from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

DUMMY_TOKENS = ["This ", "is ", "a ", "dummy ", "response."]


def _candidate(text: str, finish: bool) -> dict:
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP" if finish else None,
            }
        ]
    }


async def _stream():
    for token in DUMMY_TOKENS:
        yield f"data: {json.dumps(_candidate(token, finish=False))}\n\n"
        await asyncio.sleep(0.01)


@app.post("/v1beta/models/{model}:generateContent")
async def generate_content(model: str, request: Request):
    return _candidate("This is a dummy response.", finish=True)


@app.post("/v1beta/models/{model}:streamGenerateContent")
async def stream_generate_content(model: str, request: Request):
    return StreamingResponse(_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
