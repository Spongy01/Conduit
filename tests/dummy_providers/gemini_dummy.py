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
    text = " ".join(
        part.get("text", "")
        for content in body.get("contents", [])
        for part in content.get("parts", [])
    )
    return _estimate_tokens(text)


def _usage_metadata(prompt_tokens: int, output_tokens: int) -> dict:
    return {
        "promptTokenCount": prompt_tokens,
        "candidatesTokenCount": output_tokens,
        "totalTokenCount": prompt_tokens + output_tokens,
    }


def _candidate(text: str, finish: bool, usage_metadata: dict | None = None) -> dict:
    result = {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP" if finish else None,
            }
        ]
    }
    if usage_metadata is not None:
        result["usageMetadata"] = usage_metadata
    return result


async def _stream(body: dict):
    prompt_tokens = _prompt_tokens(body)
    for token in DUMMY_TOKENS:
        yield f"data: {json.dumps(_candidate(token, finish=False))}\n\n"
        await asyncio.sleep(0.01)

    output_tokens = _estimate_tokens(DUMMY_RESPONSE_TEXT)
    yield f"data: {json.dumps(_candidate('', finish=True, usage_metadata=_usage_metadata(prompt_tokens, output_tokens)))}\n\n"


@app.post("/v1beta/models/{model}:generateContent")
async def generate_content(model: str, request: Request):
    body = await request.json()
    prompt_tokens = _prompt_tokens(body)
    output_tokens = _estimate_tokens(DUMMY_RESPONSE_TEXT)
    return _candidate(
        "This is a dummy response.",
        finish=True,
        usage_metadata=_usage_metadata(prompt_tokens, output_tokens),
    )


@app.post("/v1beta/models/{model}:streamGenerateContent")
async def stream_generate_content(model: str, request: Request):
    body = await request.json()
    return StreamingResponse(_stream(body), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
