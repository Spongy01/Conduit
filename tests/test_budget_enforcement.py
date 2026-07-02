import asyncio

import pytest

TEAM_PAYLOAD = {
    "api_key": "sk-test-budget",
    "team_id": "team_budget",
    "team_name": "Budget Team",
    "allowed_models": ["gpt-4o"],
    "rate_limit": 100,
    "budget_limit": 10.0,
    "budget_period": "monthly",
}


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


# ─── reserve_budget ────────────────────────────────────────────────────────

async def test_reserve_budget_within_limit(db_conn, budget_db):
    api_key = await _seed_team(db_conn)

    result = await budget_db.reserve_budget(api_key, 4.0)

    assert result["approved"] is True
    assert result["reservation_id"] is not None

    team_row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert team_row["current_spend"] == pytest.approx(4.0)

    reservation_row = await db_conn.fetchrow(
        "SELECT * FROM reservations WHERE id = $1", result["reservation_id"]
    )
    assert reservation_row is not None
    assert reservation_row["api_key"] == api_key
    assert float(reservation_row["reserved_amount"]) == pytest.approx(4.0)


async def test_reserve_budget_exceeds_limit(db_conn, budget_db):
    api_key = await _seed_team(db_conn, budget_limit=10.0)
    await budget_db.reserve_budget(api_key, 8.0)

    with pytest.raises(ValueError, match="Budget limit exceeded"):
        await budget_db.reserve_budget(api_key, 3.0)

    # Rejected reservation must not have moved current_spend or left a row behind.
    team_row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert team_row["current_spend"] == pytest.approx(8.0)

    count = await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", api_key)
    assert count == 1


async def test_reserve_budget_unknown_api_key(budget_db):
    with pytest.raises(ValueError, match="does not exist"):
        await budget_db.reserve_budget("sk-nonexistent", 1.0)


async def test_reserve_budget_concurrent_requests_respect_limit(db_conn, budget_db):
    api_key = await _seed_team(db_conn, budget_limit=10.0)

    results = await asyncio.gather(
        *[budget_db.reserve_budget(api_key, 4.0) for _ in range(4)],
        return_exceptions=True,
    )

    approved = [r for r in results if isinstance(r, dict)]
    rejected = [r for r in results if isinstance(r, ValueError)]

    # Only 2 of the 4 concurrent $4 reservations can fit in a $10 budget.
    assert len(approved) == 2
    assert len(rejected) == 2

    team_row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert team_row["current_spend"] == pytest.approx(8.0)


# ─── settle_budget ─────────────────────────────────────────────────────────

async def test_settle_budget_actual_higher_than_reserved(db_conn, budget_db):
    api_key = await _seed_team(db_conn, budget_limit=10.0)
    reservation = await budget_db.reserve_budget(api_key, 3.0)

    result = await budget_db.settle_budget(api_key, reservation["reservation_id"], 5.0)

    assert result == {"settled": True, "actual_spend": 5.0}

    team_row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert team_row["current_spend"] == pytest.approx(5.0)

    reservation_row = await db_conn.fetchrow(
        "SELECT * FROM reservations WHERE id = $1", reservation["reservation_id"]
    )
    assert reservation_row is None


async def test_settle_budget_actual_lower_than_reserved(db_conn, budget_db):
    api_key = await _seed_team(db_conn, budget_limit=10.0)
    reservation = await budget_db.reserve_budget(api_key, 5.0)

    await budget_db.settle_budget(api_key, reservation["reservation_id"], 2.0)

    team_row = await db_conn.fetchrow("SELECT current_spend FROM teams WHERE api_key = $1", api_key)
    assert team_row["current_spend"] == pytest.approx(2.0)


async def test_settle_budget_unknown_reservation(db_conn, budget_db):
    api_key = await _seed_team(db_conn)

    with pytest.raises(ValueError, match="Reservation not found"):
        await budget_db.settle_budget(api_key, "00000000-0000-0000-0000-000000000000", 1.0)
