"""Model catalog: thin pass-through to the database layer for managing
which models the gateway knows about and their per-token pricing."""
from gateway.core.database import db

async def add_model(model_name: str, provider: str, cost_per_input_token: float, cost_per_output_token: float, tier: int = 1) -> None:
    """
    Adds a new model to the source of truth (the stub dict for now,
    Postgres later).
    """
    try:
        await db.add_model(model_name, provider, cost_per_input_token, cost_per_output_token, tier)
    except ValueError as e:
        raise ValueError(str(e))

    return await get_model_config(model_name)


async def update_model(model_name: str, **fields) -> dict:
    """Updates the given fields (e.g. pricing) for an existing model and
    returns its refreshed config. Raises ValueError if unknown."""
    try:
        await db.update_model(model_name, **fields)
    except ValueError as e:
        raise ValueError(str(e))

    return await get_model_config(model_name)


async def delete_model(model_name: str) -> None:
    """Removes a model from the catalog. Raises ValueError if unknown."""
    try:
        await db.delete_model(model_name)
    except ValueError as e:
        raise ValueError(str(e))

async def get_model_config(model_name: str) -> dict | None:
    """
    Returns the model configuration if it exists, otherwise returns None.
    """
    return await db.get_model(model_name)