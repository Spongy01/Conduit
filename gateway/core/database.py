"""Postgres access layer: owns the connection pool and every SQL
statement for teams, models, and budget reservations. This is the source
of truth that core/team_config.py and core/model_catalog.py cache in front
of."""
import asyncpg
import os

class Database:
    """Thin async wrapper around an asyncpg connection pool."""

    def __init__(self, dsn: str):
        self.dsn = dsn  # data source name: postgresql://user:password@host:port/database ||
                        # has everything in a line insteaad of passing each parameter separately
        self.pool = None

    async def connect(self):
        """Creates the connection pool. Must be called before any query
        method is used (see main.py's lifespan handler)."""
        self.pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=5,
                max_size=25)

    async def disconnect(self):
        """Closes the connection pool on application shutdown."""
        if self.pool:
            await self.pool.close()


    ## Database Operations for Teams
    async def create_team(self, api_key: str, team_id: str, team_name: str, allowed_models: list[str], rate_limit: int, budget_limit: float, budget_period: str = "monthly"):
        """Inserts a new team row. Raises ValueError if api_key already exists."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Insert the new team into the database
                try:
                    await connection.execute(
                            """
                            INSERT INTO teams (api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period)
                            VALUES ($1, $2, $3, $4, $5, $6, $7)
                            """,
                            api_key, team_id, team_name, allowed_models, rate_limit, budget_limit, budget_period
                        )
                except asyncpg.UniqueViolationError:
                    raise ValueError(f"API key {api_key} already exists")
                
            
    async def update_team(self, api_key: str, **fields):
        """Updates only the given columns for a team. Raises ValueError if
        the api_key doesn't exist. `fields` keys are trusted to be valid
        column names (validated upstream by the Pydantic request models)."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Check if the team exists
                team = await connection.fetchrow("SELECT * FROM teams WHERE api_key = $1", api_key)
                if not team:
                    raise ValueError(f"API key {api_key} does not exist")

                # Prepare the update statement dynamically based on provided fields
                set_clauses = []
                values = []
                for i, (field, value) in enumerate(fields.items(), start=1):
                    set_clauses.append(f"{field} = ${i}")
                    values.append(value)

                if set_clauses:
                    set_clause_str = ", ".join(set_clauses)
                    
                await connection.execute(
                    f"UPDATE teams SET {set_clause_str} WHERE api_key = ${len(values) + 1}",
                    *values, api_key
                )

    

    async def revoke_team(self, api_key: str):
        """Permanently deletes a team row. Raises ValueError if it doesn't exist."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Check if the team exists
                team = await connection.fetchrow("SELECT * FROM teams WHERE api_key = $1", api_key)
                if not team:
                    raise ValueError(f"API key {api_key} does not exist")

                # Delete the team from the database
                
                await connection.execute("DELETE FROM teams WHERE api_key = $1", api_key)
    
    async def get_team(self, api_key: str):
        """Returns the team row as a dict, or None if the api_key is unknown."""
        async with self.pool.acquire() as connection:
            team = await connection.fetchrow("SELECT * FROM teams WHERE api_key = $1", api_key)
            if not team:
                return None
            return dict(team)


    ## Database Operations for Models
    async def add_model(self, model_name: str, provider: str, cost_per_input_token: float, cost_per_output_token: float, tier: int = 1):
        """Inserts a new model row. Raises ValueError if model_name already exists."""
        async with self.pool.acquire() as connection:
            # Insert the new model into the database
            try:
                await connection.execute(
                    """
                    INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token, tier)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    model_name, provider, cost_per_input_token, cost_per_output_token, tier
                )
            except asyncpg.UniqueViolationError:
                raise ValueError(f"Model {model_name} already exists")
    
    async def update_model(self, model_name: str, **fields):
        """Updates only the given columns for a model. Raises ValueError if
        model_name doesn't exist."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Check if the model exists
                model = await connection.fetchrow("SELECT * FROM models WHERE name = $1", model_name)
                if not model:
                    raise ValueError(f"Model {model_name} does not exist")

                # Prepare the update statement dynamically based on provided fields
                set_clauses = []
                values = []
                for i, (field, value) in enumerate(fields.items(), start=1):
                    set_clauses.append(f"{field} = ${i}")
                    values.append(value)

                if set_clauses:
                    set_clause_str = ", ".join(set_clauses)
                    
                await connection.execute(
                    f"UPDATE models SET {set_clause_str} WHERE name = ${len(values) + 1}",
                    *values, model_name
                )
    
    async def delete_model(self, model_name: str):
        """Permanently deletes a model row. Raises ValueError if it doesn't exist."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Check if the model exists
                model = await connection.fetchrow("SELECT * FROM models WHERE name = $1", model_name)
                if not model:
                    raise ValueError(f"Model {model_name} does not exist")

                # Delete the model from the database
                await connection.execute("DELETE FROM models WHERE name = $1", model_name)

    
    async def get_model(self, model_name: str):
        """Returns the model row as a dict, or None if model_name is unknown."""
        async with self.pool.acquire() as connection:
            model = await connection.fetchrow("SELECT * FROM models WHERE name = $1", model_name)
            if not model:
                return None
            return dict(model)


    ## Database Operations for Budget Enforcement
    async def reserve_budget(self, api_key: str, amount: float) -> dict:
        """Atomically reserves `amount` against a team's remaining budget
        and records it as a pending reservation, to be finalized later by
        settle_budget once the actual cost is known."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Check if the team exists
                team = await connection.fetchrow("SELECT * FROM teams WHERE api_key = $1", api_key)
                if not team:
                    raise ValueError(f"API key {api_key} does not exist")

                # Atomically reserve the amount only if it stays within budget_limit,
                # so concurrent reservations for the same team can't both pass a
                # separate read-then-write check.
                row = await connection.fetchrow(
                    """
                    UPDATE teams
                    SET current_spend = current_spend + $1
                    WHERE api_key = $2 AND current_spend + $1 <= budget_limit
                    RETURNING api_key
                    """,
                    amount, api_key
                )
                if not row:
                    raise ValueError("Budget limit exceeded")

                reservation = await connection.fetchrow(
                    """
                    INSERT INTO reservations (api_key, reserved_amount)
                    VALUES ($1, $2)
                    RETURNING id
                    """,
                    api_key, amount
                )

                return {"approved": True, "reservation_id": reservation["id"]}

    async def settle_budget(self, api_key: str, reservation_id: str, actual_spend: float) -> dict:
        """Replaces a pending reservation with the actual spend: removes the
        reservation row and adjusts current_spend by the delta between what
        was reserved and what was actually used (can be positive or negative)."""
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                reservation = await connection.fetchrow(
                    "SELECT * FROM reservations WHERE id = $1 AND api_key = $2", reservation_id, api_key
                )
                if not reservation:
                    raise ValueError("Reservation not found")

                await connection.execute("DELETE FROM reservations WHERE id = $1", reservation_id)

                delta = actual_spend - float(reservation["reserved_amount"])
                await connection.execute(
                    "UPDATE teams SET current_spend = current_spend + $1 WHERE api_key = $2",
                    delta, api_key
                )

                return {"settled": True, "actual_spend": actual_spend}



# when using compose, set postgres rather than localhost, and use the password set in the docker-compose.yml file
db = Database(dsn=os.environ.get("DATABASE_URL", "postgresql://conduit:postgres_conduit@localhost:5432/conduit"))