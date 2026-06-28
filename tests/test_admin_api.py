import pytest

TEAM_PAYLOAD = {
    "api_key": "sk-test-abc123",
    "team_id": "team_test",
    "team_name": "Test Team",
    "allowed_models": ["gpt-4o"],
    "rate_limit": 100,
    "budget_limit": 10.0,
    "budget_period": "monthly",
}


# ─── Team Tests ──────────────────────────────────────────────────────────────

async def test_create_team(client, db_conn, admin_headers):
    r = await client.post("/admin/v1/teams", json=TEAM_PAYLOAD, headers=admin_headers)
    assert r.status_code == 200

    row = await db_conn.fetchrow(
        "SELECT * FROM teams WHERE api_key = $1", TEAM_PAYLOAD["api_key"]
    )
    assert row is not None
    assert row["team_name"] == "Test Team"
    assert list(row["allowed_models"]) == ["gpt-4o"]
    assert row["rate_limit"] == 100
    assert row["budget_limit"] == pytest.approx(10.0)
    assert row["budget_period"] == "monthly"


async def test_create_team_duplicate_key(client, db_conn, admin_headers):
    await client.post("/admin/v1/teams", json=TEAM_PAYLOAD, headers=admin_headers)
    r = await client.post("/admin/v1/teams", json=TEAM_PAYLOAD, headers=admin_headers)
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


async def test_update_team(client, db_conn, admin_headers):
    await client.post("/admin/v1/teams", json=TEAM_PAYLOAD, headers=admin_headers)

    r = await client.patch(
        f"/admin/v1/teams/{TEAM_PAYLOAD['api_key']}",
        json={"team_name": "Updated Team", "rate_limit": 200},
        headers=admin_headers,
    )
    assert r.status_code == 200

    row = await db_conn.fetchrow(
        "SELECT * FROM teams WHERE api_key = $1", TEAM_PAYLOAD["api_key"]
    )
    assert row["team_name"] == "Updated Team"
    assert row["rate_limit"] == 200


async def test_update_team_not_found(client, admin_headers):
    r = await client.patch(
        "/admin/v1/teams/sk-nonexistent",
        json={"team_name": "Ghost"},
        headers=admin_headers,
    )
    assert r.status_code == 400
    assert "does not exist" in r.json()["detail"]


async def test_revoke_team(client, db_conn, admin_headers):
    await client.post("/admin/v1/teams", json=TEAM_PAYLOAD, headers=admin_headers)

    r = await client.delete(
        f"/admin/v1/teams/{TEAM_PAYLOAD['api_key']}", headers=admin_headers
    )
    assert r.status_code == 200

    row = await db_conn.fetchrow(
        "SELECT * FROM teams WHERE api_key = $1", TEAM_PAYLOAD["api_key"]
    )
    assert row is None


async def test_revoke_team_not_found(client, admin_headers):
    r = await client.delete(
        "/admin/v1/teams/sk-nonexistent", headers=admin_headers
    )
    assert r.status_code == 404
    assert "does not exist" in r.json()["detail"]
