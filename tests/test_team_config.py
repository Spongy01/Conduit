import pytest

from gateway.core import team_config


async def test_get_team_config_enriches_tier(db_conn):
    await db_conn.execute(
        "INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token, tier) VALUES ($1, $2, $3, $4, $5)",
        "tiered-gpt", "openai", 0.001, 0.002, 3,
    )
    await db_conn.execute(
        """
        INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        "sk-test-team-config", "team_tc", "TC Team", ["tiered-gpt"], 100, 10.0, "monthly",
    )

    team = await team_config.get_team_config("sk-test-team-config")

    assert team is not None
    assert team["allowed_models"] == [
        {
            "name": "tiered-gpt",
            "provider": "openai",
            "cost_per_input_token": pytest.approx(0.001),
            "cost_per_output_token": pytest.approx(0.002),
            "tier": 3,
        }
    ]
