"""Resolves which provider client should handle a given chat request,
based on the provider tag attached to the model in the team's allowlist."""
import logging
from gateway.core.providers import PROVIDERS
from gateway.core.schema import ChatCompletionRequest
from fastapi import HTTPException

logger = logging.getLogger(__name__)

def route_request(request: ChatCompletionRequest, team: dict):
    """
    Route the request to the appropriate provider based on the model.
    """
    model = request.model
    provider_name = None

    # fetch provider name from the team's allowed models
    for allowed_model in team.get("allowed_models", []):
        if allowed_model["name"] == model:
            provider_name = allowed_model["provider"]
            break

    # Get the provider instance
    provider = PROVIDERS.get(provider_name)
    if not provider:
        # if no provider, can't route, raise an error
        logger.error("No provider found for model '%s' (provider_name=%s)", model, provider_name)
        raise HTTPException(status_code=500, detail=f"No provider found for model '{model}'.")

    logger.debug("Routed model='%s' to provider='%s'", model, provider_name)
    # Call the provider's method to handle the request
    return provider