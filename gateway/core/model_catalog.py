from gateway.core.database import db

async def add_model(model_name: str, provider: str, cost_per_input_token: float, cost_per_output_token: float) -> None:
    """
    Adds a new model to the source of truth (the stub dict for now,
    Postgres later).
    """
    try:
        await db.add_model(model_name, provider, cost_per_input_token, cost_per_output_token)
    except ValueError as e:
        raise ValueError(str(e))

    return await get_model_config(model_name)


async def update_model(model_name: str, **fields) -> dict:
    try:
        await db.update_model(model_name, **fields)
    except ValueError as e:
        raise ValueError(str(e))

    return await get_model_config(model_name)


async def delete_model(model_name: str) -> None:
    try:
        await db.delete_model(model_name)
    except ValueError as e:
        raise ValueError(str(e))

async def get_model_config(model_name: str) -> dict | None:
    """
    Returns the model configuration if it exists, otherwise returns None.
    """
    return await db.get_model(model_name)