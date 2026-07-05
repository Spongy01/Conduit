# functions called by chat.py to check if the team has exceeded their budget
# these functions call the database functions in database.py to reserve and settle budget

import logging

from gateway.core.database import db
from gateway.core.schema import ChatCompletionRequest
from gateway.core.tokens import estimate_tokens

logger = logging.getLogger(__name__)


def _model_costs(team: dict, model: str) -> dict:
    """Looks up the pricing dict for `model` within a team's enriched
    allowed_models list. Raises ValueError if the team isn't allowed to use it."""
    for allowed_model in team.get("allowed_models", []):
        if allowed_model["name"] == model:
            return allowed_model
    raise ValueError(f"Model '{model}' is not in team's allowed_models")


async def reserve_budget(api_key: str, team: dict, request: ChatCompletionRequest) -> dict:
    """
    Estimates the cost of a chat completion call and reserves it against the
    team's budget. Input tokens are estimated from the request's message text
    (~4 chars/token); output tokens are estimated as request.max_tokens (the
    worst case, since the real output isn't known before the call).

    Raises ValueError if the api_key is unknown or the reservation would
    exceed the team's budget_limit (propagated from db.reserve_budget).
    """
    model_costs = _model_costs(team, request.model)

    input_text = " ".join(m.content for m in request.messages)
    estimated_input_tokens = estimate_tokens(input_text)
    estimated_output_tokens = request.max_tokens

    estimated_cost = (
        estimated_input_tokens * model_costs["cost_per_input_token"]
        + estimated_output_tokens * model_costs["cost_per_output_token"]
    )

    logger.debug(
        "Reserving budget api_key=%s model=%s estimated_input_tokens=%s estimated_output_tokens=%s estimated_cost=%s",
        api_key, request.model, estimated_input_tokens, estimated_output_tokens, estimated_cost,
    )

    return await db.reserve_budget(api_key, estimated_cost)


async def settle_budget(
    api_key: str, model: str, team: dict, reservation_id: str, input_tokens: int, output_tokens: int
) -> dict:
    """
    Reconciles a reservation against the actual token usage of a completed
    call. Raises ValueError if the reservation_id is unknown (propagated
    from db.settle_budget).
    """
    model_costs = _model_costs(team, model)

    actual_cost = (
        input_tokens * model_costs["cost_per_input_token"]
        + output_tokens * model_costs["cost_per_output_token"]
    )

    logger.debug(
        "Settling budget api_key=%s model=%s reservation_id=%s input_tokens=%s output_tokens=%s actual_cost=%s",
        api_key, model, reservation_id, input_tokens, output_tokens, actual_cost,
    )

    return await db.settle_budget(api_key, reservation_id, actual_cost)


async def release_budget(api_key: str, reservation_id: str) -> dict:
    """
    Cancels a reservation that was made for a provider attempt that failed
    before completing, refunding its reserved amount. Unlike settle_budget,
    no token counts are involved — the call never produced usage to bill.
    Raises ValueError if the reservation_id is unknown (propagated from
    db.release_budget).
    """
    logger.debug("Releasing budget api_key=%s reservation_id=%s", api_key, reservation_id)
    return await db.release_budget(api_key, reservation_id)
