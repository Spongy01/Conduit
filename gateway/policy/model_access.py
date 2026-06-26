from gateway.core.schema import ChatCompletionRequest
from fastapi import HTTPException

def raise_if_model_not_allowed(request: ChatCompletionRequest, team: dict):
    model = request.model
    allowed_models = team.get("allowed_models", [])
    # allowed models is a list of dicts with 'name' key, so we extract the names
    allowed_model_names = [m["name"] for m in allowed_models]   
    if model not in allowed_model_names:
        raise HTTPException(status_code=403, detail=f"Model '{model}' is not allowed. Allowed models: {allowed_model_names}")
