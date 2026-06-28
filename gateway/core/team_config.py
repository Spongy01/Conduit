from gateway.core.database import db
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

async def create_team(
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
    try:
        await db.create_team(
            api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period
        )
    except ValueError as e:
        raise ValueError(str(e))
    return await get_team_config(api_key)


# update key data function

async def update_team(api_key: str, **fields) -> dict:
    
    try:
        await db.update_team(api_key, **fields)
    except ValueError as e:
        raise ValueError(str(e))

    return await get_team_config(api_key)


# revoke key function

async def revoke_team(api_key: str) -> None:
    try:
        await db.revoke_team(api_key)
    except ValueError as e:
        raise ValueError(str(e))



async def get_team_config(api_key: str) -> dict | None:
    """
    Returns the team configuration if it exists, otherwise returns None.
    """
    return await db.get_team(api_key)
