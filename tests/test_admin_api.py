import uuid

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
    assert r.status_code == 404
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


MODEL_PAYLOAD = {
    "model_name": "gpt-4o-test",
    "provider": "openai",
    "cost_per_input_token": 0.000005,
    "cost_per_output_token": 0.000015,
}


# ─── Model Tests ─────────────────────────────────────────────────────────────

async def test_create_model(client, db_conn, admin_headers):
    r = await client.post("/admin/v1/models", json=MODEL_PAYLOAD, headers=admin_headers)
    assert r.status_code == 200

    row = await db_conn.fetchrow(
        "SELECT * FROM models WHERE name = $1", MODEL_PAYLOAD["model_name"]
    )
    assert row is not None
    assert row["provider"] == "openai"
    assert row["cost_per_input_token"] == pytest.approx(0.000005)
    assert row["cost_per_output_token"] == pytest.approx(0.000015)


async def test_create_model_duplicate(client, db_conn, admin_headers):
    await client.post("/admin/v1/models", json=MODEL_PAYLOAD, headers=admin_headers)
    r = await client.post("/admin/v1/models", json=MODEL_PAYLOAD, headers=admin_headers)
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


async def test_update_model(client, db_conn, admin_headers):
    await client.post("/admin/v1/models", json=MODEL_PAYLOAD, headers=admin_headers)

    r = await client.patch(
        f"/admin/v1/models/{MODEL_PAYLOAD['model_name']}",
        json={
            "model_name": MODEL_PAYLOAD["model_name"],
            "provider": "openai",
            "cost_per_input_token": 0.000001,
            "cost_per_output_token": 0.000002,
        },
        headers=admin_headers,
    )
    assert r.status_code == 200

    row = await db_conn.fetchrow(
        "SELECT * FROM models WHERE name = $1", MODEL_PAYLOAD["model_name"]
    )
    assert row["cost_per_input_token"] == pytest.approx(0.000001)
    assert row["cost_per_output_token"] == pytest.approx(0.000002)


async def test_update_model_not_found(client, admin_headers):
    r = await client.patch(
        "/admin/v1/models/nonexistent-model",
        json={
            "model_name": "nonexistent-model",
            "provider": "openai",
            "cost_per_input_token": 0.0,
            "cost_per_output_token": 0.0,
        },
        headers=admin_headers,
    )
    assert r.status_code == 404
    assert "does not exist" in r.json()["detail"]


async def test_delete_model(client, db_conn, admin_headers):
    await client.post("/admin/v1/models", json=MODEL_PAYLOAD, headers=admin_headers)

    r = await client.delete(
        f"/admin/v1/models/{MODEL_PAYLOAD['model_name']}", headers=admin_headers
    )
    assert r.status_code == 200

    row = await db_conn.fetchrow(
        "SELECT * FROM models WHERE name = $1", MODEL_PAYLOAD["model_name"]
    )
    assert row is None


async def test_delete_model_not_found(client, admin_headers):
    r = await client.delete(
        "/admin/v1/models/nonexistent-model", headers=admin_headers
    )
    assert r.status_code == 404
    assert "does not exist" in r.json()["detail"]


async def test_create_model_with_tier(client, db_conn, admin_headers):
    payload = {
        "model_name": "tiered-model",
        "provider": "openai",
        "cost_per_input_token": 0.001,
        "cost_per_output_token": 0.002,
        "tier": 3,
    }
    r = await client.post("/admin/v1/models", json=payload, headers=admin_headers)
    assert r.status_code == 200

    row = await db_conn.fetchrow("SELECT * FROM models WHERE name = $1", "tiered-model")
    assert row["tier"] == 3


async def test_create_model_default_tier(client, db_conn, admin_headers):
    payload = {
        "model_name": "default-tier-model",
        "provider": "openai",
    }
    r = await client.post("/admin/v1/models", json=payload, headers=admin_headers)
    assert r.status_code == 200

    row = await db_conn.fetchrow("SELECT * FROM models WHERE name = $1", "default-tier-model")
    assert row["tier"] == 1


# ─── Admin authentication ────────────────────────────────────────────────────

async def test_admin_wrong_key_returns_401(client):
    r = await client.post("/admin/v1/teams", json=TEAM_PAYLOAD, headers={"X-Admin-Key": "wrong-key"})
    assert r.status_code == 401


async def test_admin_missing_key_is_rejected(client):
    r = await client.post("/admin/v1/teams", json=TEAM_PAYLOAD)
    assert r.status_code == 422  # required header absent; never reaches the handler


async def test_admin_non_ascii_key_returns_401_not_500(client):
    """secrets.compare_digest raises TypeError on non-ASCII *str* input, so
    require_admin must encode both sides to bytes. Sent as raw bytes so the
    non-ASCII value actually reaches the server."""
    r = await client.post(
        "/admin/v1/teams", json=TEAM_PAYLOAD, headers={"X-Admin-Key": "clé-é-密".encode("utf-8")}
    )
    assert r.status_code == 401


# ─── List endpoints (used by the admin page) ─────────────────────────────────

def _team(api_key, name, models=("gpt-4o",)):
    return {**TEAM_PAYLOAD, "api_key": api_key, "team_id": f"id-{api_key}", "team_name": name,
            "allowed_models": list(models)}


async def test_list_teams_returns_sorted_teams_with_float_spend(client, admin_headers):
    await client.post("/admin/v1/teams", json=_team("sk-b", "Beta"), headers=admin_headers)
    await client.post("/admin/v1/teams", json=_team("sk-a", "Alpha"), headers=admin_headers)

    r = await client.get("/admin/v1/teams", headers=admin_headers)

    assert r.status_code == 200
    teams = r.json()["teams"]
    assert [t["team_name"] for t in teams] == ["Alpha", "Beta"]
    assert teams[0]["api_key"] == "sk-a"
    assert set(teams[0]) == {"api_key", "team_id", "team_name", "allowed_models", "rate_limit",
                             "budget_limit", "budget_period", "current_spend"}
    assert isinstance(teams[0]["current_spend"], (int, float))


async def test_list_teams_empty(client, admin_headers):
    r = await client.get("/admin/v1/teams", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"teams": []}


async def test_list_teams_keeps_names_of_unregistered_models(client, admin_headers):
    await client.post("/admin/v1/teams", json=_team("sk-g", "Ghost", models=["ghost-model"]), headers=admin_headers)

    r = await client.get("/admin/v1/teams", headers=admin_headers)

    assert r.json()["teams"][0]["allowed_models"] == ["ghost-model"]


async def test_list_models_returns_sorted_models_with_costs(client, admin_headers):
    await client.post("/admin/v1/models", headers=admin_headers,
                      json={"model_name": "zeta", "provider": "ollama", "tier": 2})
    await client.post("/admin/v1/models", headers=admin_headers,
                      json={"model_name": "alpha", "provider": "openai", "cost_per_input_token": 0.5,
                            "cost_per_output_token": 1.5, "tier": 4})

    r = await client.get("/admin/v1/models", headers=admin_headers)

    assert r.status_code == 200
    assert r.json()["models"] == [
        {"name": "alpha", "provider": "openai", "tier": 4, "cost_per_input_token": 0.5, "cost_per_output_token": 1.5},
        {"name": "zeta", "provider": "ollama", "tier": 2, "cost_per_input_token": 0.0, "cost_per_output_token": 0.0},
    ]


async def test_list_models_empty(client, admin_headers):
    r = await client.get("/admin/v1/models", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"models": []}


async def test_list_endpoints_require_admin_key(client):
    for path in ("/admin/v1/teams", "/admin/v1/models"):
        assert (await client.get(path)).status_code == 422
        assert (await client.get(path, headers={"X-Admin-Key": "wrong"})).status_code == 401


async def test_patch_team_with_empty_body_leaves_team_unchanged(client, admin_headers):
    await client.post("/admin/v1/teams", json=TEAM_PAYLOAD, headers=admin_headers)

    r = await client.patch(f"/admin/v1/teams/{TEAM_PAYLOAD['api_key']}", json={}, headers=admin_headers)

    assert r.status_code == 200
    assert r.json()["team_name"] == TEAM_PAYLOAD["team_name"]
    # PATCH returns the Redis-cached config, where numbers come back as strings.
    assert float(r.json()["rate_limit"]) == TEAM_PAYLOAD["rate_limit"]


async def test_model_name_with_slashes_can_be_patched_and_deleted(client, admin_headers):
    name = "hf.co/user/model:tag"
    created = await client.post("/admin/v1/models", headers=admin_headers,
                                json={"model_name": name, "provider": "ollama", "tier": 1})
    assert created.status_code == 200

    patched = await client.patch(f"/admin/v1/models/{name}", headers=admin_headers,
                                 json={"model_name": name, "provider": "ollama", "tier": 3})
    assert patched.status_code == 200
    assert patched.json()["tier"] == 3

    deleted = await client.delete(f"/admin/v1/models/{name}", headers=admin_headers)
    assert deleted.status_code == 200


# ─── Cache invalidation: admin changes must reach the chat API immediately ───

async def _models_for(client, api_key):
    r = await client.get("/api/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    return r.status_code, ([m["name"] for m in r.json()["models"]] if r.status_code == 200 else None)


async def test_editing_a_team_takes_effect_immediately_despite_the_cache(client, admin_headers):
    for name in ("m-one", "m-two"):
        await client.post("/admin/v1/models", headers=admin_headers, json={"model_name": name, "provider": "ollama"})
    # Unique key: team configs are cached in Redis for 90s and nothing clears it between tests.
    key = f"sk-cache-{uuid.uuid4().hex[:12]}"
    await client.post("/admin/v1/teams", headers=admin_headers, json={**TEAM_PAYLOAD, "api_key": key, "allowed_models": ["m-one"]})
    assert await _models_for(client, key) == (200, ["m-one"])  # now cached

    await client.patch(f"/admin/v1/teams/{key}", headers=admin_headers, json={"allowed_models": ["m-two"]})

    assert await _models_for(client, key) == (200, ["m-two"])


async def test_revoked_team_key_is_rejected_immediately_despite_the_cache(client, admin_headers):
    await client.post("/admin/v1/models", headers=admin_headers, json={"model_name": "m-one", "provider": "ollama"})
    key = f"sk-cache-{uuid.uuid4().hex[:12]}"
    await client.post("/admin/v1/teams", headers=admin_headers, json={**TEAM_PAYLOAD, "api_key": key, "allowed_models": ["m-one"]})
    assert await _models_for(client, key) == (200, ["m-one"])  # now cached

    await client.delete(f"/admin/v1/teams/{key}", headers=admin_headers)

    assert (await _models_for(client, key))[0] == 401


# ─── Review fixes: revoke with open reservations; no key in error messages ───

async def test_revoking_a_team_with_an_open_reservation_succeeds(client, db_conn, admin_headers):
    """A chat request in flight (or a leaked reservation) must not block revoking
    a team: the foreign key from reservations used to turn this into a 500 and
    leave the key valid."""
    key = f"sk-revoke-{uuid.uuid4().hex[:12]}"
    await client.post("/admin/v1/teams", headers=admin_headers, json={**TEAM_PAYLOAD, "api_key": key, "allowed_models": []})
    await db_conn.execute("INSERT INTO reservations (api_key, reserved_amount) VALUES ($1, 0.5)", key)

    r = await client.delete(f"/admin/v1/teams/{key}", headers=admin_headers)

    assert r.status_code == 200
    assert await db_conn.fetchval("SELECT COUNT(*) FROM teams WHERE api_key = $1", key) == 0
    assert await db_conn.fetchval("SELECT COUNT(*) FROM reservations WHERE api_key = $1", key) == 0
    assert (await _models_for(client, key))[0] == 401


async def test_admin_error_messages_do_not_echo_the_api_key(client, admin_headers):
    key = f"sk-secret-{uuid.uuid4().hex[:12]}"
    await client.post("/admin/v1/teams", headers=admin_headers, json={**TEAM_PAYLOAD, "api_key": key})

    duplicate = await client.post("/admin/v1/teams", headers=admin_headers, json={**TEAM_PAYLOAD, "api_key": key})
    missing = f"sk-missing-{uuid.uuid4().hex[:12]}"
    patched = await client.patch(f"/admin/v1/teams/{missing}", headers=admin_headers, json={"rate_limit": 5})
    revoked = await client.delete(f"/admin/v1/teams/{missing}", headers=admin_headers)

    assert duplicate.status_code == 400 and "already exists" in duplicate.json()["detail"]
    assert patched.status_code == 404 and revoked.status_code == 404
    for response, secret in ((duplicate, key), (patched, missing), (revoked, missing)):
        assert secret not in response.json()["detail"]
