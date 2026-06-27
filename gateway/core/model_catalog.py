from gateway.core.team_config import MODELS


def add_model(model_name: str, provider: str, cost_per_input_token: float, cost_per_output_token: float) -> None:
    """
    Adds a new model to the source of truth (the stub dict for now,
    Postgres later).
    """
    if model_name in MODELS:
        raise ValueError(f"Model {model_name} already exists")

    MODELS[model_name] = {
        "provider": provider,
        "cost_per_input_token": cost_per_input_token,
        "cost_per_output_token": cost_per_output_token,
    }

    return get_model_config(model_name)


def update_model(model_name: str, **fields) -> dict:
    if model_name not in MODELS:
        raise ValueError(f"Model {model_name} does not exist")

    for field, value in fields.items():
        if field in MODELS[model_name]:
            MODELS[model_name][field] = value

    return get_model_config(model_name)


def delete_model(model_name: str) -> None:
    if model_name not in MODELS:
        raise ValueError(f"Model {model_name} does not exist")

    del MODELS[model_name]

def get_model_config(model_name: str) -> dict | None:
    """
    Returns the model configuration if it exists, otherwise returns None.
    """
    model = MODELS.get(model_name)
    if model is None:
        return None

    return {
        "name": model_name,
        "provider": model["provider"],
        "cost_per_input_token": model["cost_per_input_token"],
        "cost_per_output_token": model["cost_per_output_token"],
    }