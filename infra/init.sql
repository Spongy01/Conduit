-- Bootstraps the schema on a fresh Postgres data volume. Mounted into
-- /docker-entrypoint-initdb.d/, so the official postgres image only runs
-- this once, the first time the container starts against an empty data
-- directory (see infra/docker-compose.yaml's postgres service).
CREATE TABLE IF NOT EXISTS teams (
    api_key TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    team_name TEXT NOT NULL,
    allowed_models TEXT[] NOT NULL,
    rate_limit INTEGER NOT NULL,
    budget_limit FLOAT NOT NULL,
    budget_period TEXT NOT NULL DEFAULT 'monthly',
    current_spend NUMERIC(10, 2) DEFAULT 0.00
);

CREATE TABLE IF NOT EXISTS models (
    name TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    cost_per_input_token FLOAT NOT NULL DEFAULT 0.0,
    cost_per_output_token FLOAT NOT NULL DEFAULT 0.0,
    tier INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key TEXT REFERENCES teams(api_key),
    reserved_amount NUMERIC(10, 8),
    reserved_at TIMESTAMP NOT NULL DEFAULT now()
);
