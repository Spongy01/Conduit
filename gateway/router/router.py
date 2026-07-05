"""Resolves which provider client should handle a given chat request, with
automatic fallback to another same-tier (or, if allowed, lower-tier)
provider from the team's allowed models when the first attempt fails with
a retryable error. Also owns budget reservation/release for each attempt —
chat.py only settles the reservation the router hands back."""
import logging
import random
from typing import AsyncGenerator

import httpx
from fastapi import HTTPException

from gateway.core.providers import PROVIDERS
from gateway.core.schema import ChatCompletionRequest, ChatCompletionResponse
from gateway.policy.budget import reserve_budget, release_budget

logger = logging.getLogger(__name__)

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


async def _start_attempt(provider, provider_request: ChatCompletionRequest) -> AsyncGenerator[ChatCompletionResponse, None]:
    """Starts a provider call and pulls its first item immediately, so any
    failure (HTTPException from a non-200 upstream response, or a raw httpx
    connection/timeout error) surfaces here rather than lazily on the
    caller's first iteration. On success, returns a generator that replays
    the already-pulled first item followed by the rest of the original
    generator, so no data is lost."""
    generator = provider.generate(provider_request)
    first_item = await generator.__anext__()

    async def _replay():
        yield first_item
        async for item in generator:
            yield item

    return _replay()


async def route_request(request: ChatCompletionRequest, team: dict) -> tuple[AsyncGenerator[ChatCompletionResponse, None], str]:
    """
    Attempts the requested model, then — if it fails with a retryable error
    and request.allow_fallback is True — walks an ordered list of fallback
    candidates (same tier first, other providers; lower tiers only if
    request.allow_tier_downgrade is True) until one succeeds.

    Budget is reserved before each attempt and released on every failed
    attempt; the winning attempt's reservation is left outstanding for the
    caller to settle. A budget check failing for a candidate is a soft
    skip (not raised) — the next candidate is tried instead.

    Returns (generator, reservation_id) for the winning attempt.

    Raises:
        HTTPException(403): request.model isn't in team's allowed_models.
        HTTPException: a non-retryable provider failure (400/401/403/422),
            or any retryable failure when request.allow_fallback is False —
            re-raised as-is, after releasing that attempt's reservation.
        ValueError("Budget limit exceeded"): every attempted candidate was
            skipped purely because it would exceed the team's budget.
        NoProviderAvailableError: at least one real provider attempt failed
            and no candidate (including any budget-skipped ones) succeeded.
    """
    allowed_models = team.get("allowed_models", [])
    requested = next((m for m in allowed_models if m["name"] == request.model), None)
    if requested is None:
        raise HTTPException(status_code=403, detail=f"Model '{request.model}' is not allowed.")

    candidates = [requested]
    fallback_computed = False
    budget_failures = 0
    provider_failures = 0
    index = 0

    while index < len(candidates):
        candidate = candidates[index]
        index += 1

        provider = PROVIDERS.get(candidate["provider"])
        if provider is None:
            logger.error("No provider registered for '%s' (model=%s)", candidate["provider"], candidate["name"])
            provider_failures += 1
            continue

        provider_request = request.model_copy(update={"model": candidate["name"]})

        try:
            reservation = await reserve_budget(team["api_key"], team, provider_request)
        except ValueError as e:
            logger.warning("Budget reservation denied model=%s: %s", candidate["name"], e)
            budget_failures += 1
            if request.allow_fallback and not fallback_computed:
                candidates.extend(build_fallback_candidates(
                    request.model, allowed_models, candidate["provider"], request.allow_tier_downgrade
                ))
                fallback_computed = True
            continue

        reservation_id = reservation["reservation_id"]

        try:
            generator = await _start_attempt(provider, provider_request)
            if candidate["name"] != request.model:
                logger.info("Fallback routed requested_model=%s actual_model=%s provider=%s",
                            request.model, candidate["name"], candidate["provider"])
            return generator, reservation_id
        except HTTPException as e:
            await release_budget(team["api_key"], reservation_id)
            provider_failures += 1
            logger.warning("Provider attempt failed model=%s provider=%s status=%s",
                           candidate["name"], candidate["provider"], e.status_code)

            if not is_retryable_status(e.status_code):
                raise
            if not request.allow_fallback:
                raise
            if not fallback_computed:
                candidates.extend(build_fallback_candidates(
                    request.model, allowed_models, candidate["provider"], request.allow_tier_downgrade
                ))
                fallback_computed = True
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            await release_budget(team["api_key"], reservation_id)
            provider_failures += 1
            logger.warning("Provider attempt connection error model=%s provider=%s: %s",
                           candidate["name"], candidate["provider"], e)

            if not request.allow_fallback:
                raise HTTPException(status_code=503, detail=f"Upstream connection error: {e}") from e
            if not fallback_computed:
                candidates.extend(build_fallback_candidates(
                    request.model, allowed_models, candidate["provider"], request.allow_tier_downgrade
                ))
                fallback_computed = True
        except Exception:
            await release_budget(team["api_key"], reservation_id)
            logger.error("Unexpected error during provider attempt model=%s provider=%s",
                        candidate["name"], candidate["provider"], exc_info=True)
            raise

    if provider_failures == 0 and budget_failures > 0:
        raise ValueError("Budget limit exceeded")
    raise NoProviderAvailableError(f"No available provider could serve model '{request.model}'")
