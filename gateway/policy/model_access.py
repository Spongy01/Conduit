"""Enforces per-team model allowlists on chat completion requests."""
from gateway.core.schema import ChatCompletionRequest
from fastapi import HTTPException

def raise_if_model_not_allowed(request: ChatCompletionRequest, team: dict):
    """Raises HTTP 403 if the requested model isn't in the team's
    allowed_models. No-op (returns None) if it is."""
    model = request.model
    allowed_models = team.get("allowed_models", [])
    # allowed models is a list of dicts with 'name' key, so we extract the names
    allowed_model_names = [m["name"] for m in allowed_models]
    if model not in allowed_model_names:
        raise HTTPException(status_code=403, detail=f"Model '{model}' is not allowed. Allowed models: {allowed_model_names}")
