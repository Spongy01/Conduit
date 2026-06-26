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

def create_team(
        api_key: str,
        team_id: str,
        team_name: str,
        allowed_models: list[str],
        rate_limit: int,
        budget_limit: float,
        budget_period: str = "monthly",
)-> dict:
    """
    Adds a new team to the source of truth (the stub dict for now,
    Postgres later). No Redis touch needed: a brand-new key has never
    been read before, so it's a guaranteed cache miss on first use,
    and get_team_config's existing miss-path already populates the
    cache correctly at that point.
    """
    if api_key in TEAMS:
        raise ValueError(f"API key {api_key} already exists")

    TEAMS[api_key] = {
        "team_id": team_id,
        "team_name": team_name,
        "allowed_models": allowed_models,
        "rate_limit": rate_limit,
        "budget_limit": budget_limit,
        "budget_period": budget_period,
    }

    return get_team_config(api_key)


# update key data function

def update_team(api_key: str, **fields) -> dict:
    if api_key not in TEAMS:
        raise ValueError(f"API key {api_key} does not exist")

    for field, value in fields.items():
        if field in TEAMS[api_key]:
            if field == "allowed_models":
                # Ensure that the allowed models are valid
                for model in value:
                    if model not in MODELS:
                        raise ValueError(f"Model {model} is not recognized")
            TEAMS[api_key][field] = value
    # TODO once Redis is real: overwrite this team's cached entry with
    # the freshly resolved config, e.g. redis.set(api_key, get_team_config(api_key))
 
    return get_team_config(api_key)


# revoke key function

def revoke_team(api_key: str) -> None:
    if api_key not in TEAMS:
        raise ValueError(f"API key {api_key} does not exist")

    del TEAMS[api_key]
    # TODO once Redis is real: delete this team's cached entry, e.g. redis.delete(api_key)
    

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