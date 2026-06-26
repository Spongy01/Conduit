# Dummy stand-ins for what will eventually be two Postgres tables.
# Swap these for real DB reads later without changing get_team_config's
# return shape or its callers.

MODELS = {
    "gpt-4o": {
        "provider": "openai",
        "cost_per_input_token": 0.0000025,
        "cost_per_output_token": 0.00001,
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "cost_per_input_token": 0.00000015,
        "cost_per_output_token": 0.0000006,
    },
    "claude-3-5-sonnet": {
        "provider": "anthropic",
        "cost_per_input_token": 0.000003,
        "cost_per_output_token": 0.000015,
    },
    "llama3": {
        "provider": "ollama",
        "cost_per_input_token": 0.0,
        "cost_per_output_token": 0.0,
    },
}

TEAMS = {
    "sk-conduit-abc123": {
        "team_id": "team_abc123",
        "team_name": "Acme Corp",
        "allowed_models": ["gpt-4o", "claude-3-5-sonnet"],
        "rate_limit": 100,            # requests per minute
        "budget_limit": 50.00,        # dollars
        "budget_period": "monthly",
    },
    "sk-conduit-def456": {
        "team_id": "team_def456",
        "team_name": "Scrappy Startup",
        "allowed_models": ["gpt-4o-mini", "llama3"],
        "rate_limit": 20,
        "budget_limit": 5.00,
        "budget_period": "monthly",
    },
}


def get_team_config(api_key: str) -> dict | None:
    """
    Stub for the real get_team_config. Mimics the fully-resolved shape
    the real function should return once Redis + Postgres are wired in:
    one lookup, allowed_models already joined with provider info, no
    further DB/cache calls needed by any caller.

    Returns None if the key doesn't exist (caller should treat as 401).
    """
    team = TEAMS.get(api_key)
    if team is None:
        return None

    resolved_models = [
        {"name": name, **MODELS[name]}
        for name in team["allowed_models"]
        if name in MODELS
    ]

    return {
        "team_id": team["team_id"],
        "team_name": team["team_name"],
        "allowed_models": resolved_models,
        "rate_limit": team["rate_limit"],
        "budget_limit": team["budget_limit"],
        "budget_period": team["budget_period"],
    }