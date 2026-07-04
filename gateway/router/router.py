"""Resolves which provider client should handle a given chat request,
based on the provider tag attached to the model in the team's allowlist."""
import logging
import random
from gateway.core.providers import PROVIDERS
from gateway.core.schema import ChatCompletionRequest
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def build_fallback_candidates(
    requested_model: str,
    allowed_models: list[dict],
    failed_provider: str,
    allow_tier_downgrade: bool,
) -> list[dict]:
    """
    Builds the ordered fallback plan for a request whose first attempt (on
    `failed_provider`) failed. Walks down from the requested model's tier:
    within a tier, repeatedly picks a random remaining model on a provider
    not yet used anywhere in this plan (random.choice over the shrinking
    pool); when a tier's pool is empty, moves to the next tier down only if
    `allow_tier_downgrade` is True. Only models present in `allowed_models`
    are eligible. Returns [] if `requested_model` isn't in `allowed_models`
    or no distinct-provider peers exist.
    """
    requested = next((m for m in allowed_models if m["name"] == requested_model), None)
    if requested is None:
        return []

    excluded_providers = {failed_provider}
    candidates = []
    tier = requested["tier"]

    while True:
        pool = [
            m for m in allowed_models
            if m["tier"] == tier and m["name"] != requested_model and m["provider"] not in excluded_providers
        ]
        while pool:
            choice = random.choice(pool)
            candidates.append(choice)
            excluded_providers.add(choice["provider"])
            pool = [m for m in pool if m["provider"] not in excluded_providers]

        if not allow_tier_downgrade or tier <= 1:
            break
        tier -= 1

    return candidates


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 422}


def is_retryable_status(status_code: int) -> bool:
    """True for upstream failures worth retrying on a different provider
    (rate limits and server-side errors); False for client-error responses
    that would fail identically against any provider (bad request, auth,
    validation)."""
    return status_code in RETRYABLE_STATUS_CODES


class NoProviderAvailableError(Exception):
    """Raised when every fallback candidate for a request has been
    attempted (or skipped for budget reasons) and none succeeded."""


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