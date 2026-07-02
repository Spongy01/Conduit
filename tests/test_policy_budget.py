import pytest

from gateway.core.schema import ChatCompletionRequest, Message
from gateway.policy import budget as budget_module

TEAM_PAYLOAD = {
    "api_key": "sk-test-policy-budget",
    "team_id": "team_policy_budget",
    "team_name": "Policy Budget Team",
    "allowed_models": ["gpt-4o"],
    "rate_limit": 100,
    "budget_limit": 10.0,
    "budget_period": "monthly",
}

MODEL_COSTS = {"name": "gpt-4o", "provider": "openai", "cost_per_input_token": 0.01, "cost_per_output_token": 0.02}


def _team(**overrides):
    team = {**TEAM_PAYLOAD, "allowed_models": [MODEL_COSTS]}
    team.update(overrides)
    return team


async def _seed_team(db_conn, **overrides):
    payload = {**TEAM_PAYLOAD, **overrides}
    await db_conn.execute(
        """
        INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        payload["api_key"], payload["team_id"], payload["team_name"], payload["allowed_models"],
        payload["rate_limit"], payload["budget_limit"], payload["budget_period"],
    )
    return payload["api_key"]


@pytest.fixture(autouse=True)
def _use_test_db(monkeypatch, budget_db):
    monkeypatch.setattr(budget_module, "db", budget_db)


# ─── reserve_budget ────────────────────────────────────────────────────────

async def test_reserve_budget_computes_cost_from_messages_and_max_tokens(db_conn):
    api_key = await _seed_team(db_conn, budget_limit=10.0)
    team = _team(api_key=api_key)

    # "abcdefgh" (8 chars) -> estimate_tokens = 2; max_tokens = 3
    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[Message(role="user", content="abcdefgh")],
        max_tokens=3,
    )

    result = await budget_module.reserve_budget(api_key, team, request)

    assert result["approved"] is True

    # estimated_cost = 2 * 0.01 + 3 * 0.02 = 0.08
    row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert float(row["current_spend"]) == pytest.approx(0.08)


async def test_reserve_budget_exceeds_limit_raises(db_conn):
    api_key = await _seed_team(db_conn, budget_limit=0.01)
    team = _team(api_key=api_key)

    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[Message(role="user", content="abcdefgh")],
        max_tokens=3,
    )

    with pytest.raises(ValueError, match="Budget limit exceeded"):
        await budget_module.reserve_budget(api_key, team, request)


async def test_reserve_budget_unknown_model_raises(db_conn):
    api_key = await _seed_team(db_conn)
    team = _team(api_key=api_key)

    request = ChatCompletionRequest(
        model="not-an-allowed-model",
        messages=[Message(role="user", content="hi")],
        max_tokens=3,
    )

    with pytest.raises(ValueError, match="not in team's allowed_models"):
        await budget_module.reserve_budget(api_key, team, request)


# ─── settle_budget ─────────────────────────────────────────────────────────

async def test_settle_budget_computes_actual_cost(db_conn):
    api_key = await _seed_team(db_conn, budget_limit=10.0)
    team = _team(api_key=api_key)

    request = ChatCompletionRequest(
        model="gpt-4o",
        messages=[Message(role="user", content="abcdefgh")],
        max_tokens=3,
    )
    reservation = await budget_module.reserve_budget(api_key, team, request)

    # actual: 5 input tokens, 10 output tokens -> 5*0.01 + 10*0.02 = 0.25
    result = await budget_module.settle_budget(
        api_key, "gpt-4o", team, reservation["reservation_id"], input_tokens=5, output_tokens=10
    )

    assert result["settled"] is True

    row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert float(row["current_spend"]) == pytest.approx(0.25)


async def test_settle_budget_unknown_reservation_raises(db_conn):
    api_key = await _seed_team(db_conn)
    team = _team(api_key=api_key)

    with pytest.raises(ValueError, match="Reservation not found"):
        await budget_module.settle_budget(
            api_key, "gpt-4o", team, "00000000-0000-0000-0000-000000000000", input_tokens=1, output_tokens=1
        )
