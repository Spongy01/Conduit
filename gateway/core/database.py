import asyncpg
import os

class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn  # data source name: postgresql://user:password@host:port/database || 
                        # has everything in a line insteaad of passing each parameter separately
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
                dsn=self.dsn, 
                min_size=5,
                max_size=25)

    async def disconnect(self):
        if self.pool:
            await self.pool.close()


    ## Database Operations for Teams
    async def create_team(self, api_key: str, team_id: str, team_name: str, allowed_models: list[str], rate_limit: int, budget_limit: float, budget_period: str = "monthly"):
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
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Check if the team exists
                team = await connection.fetchrow("SELECT * FROM teams WHERE api_key = $1", api_key)
                if not team:
                    raise ValueError(f"API key {api_key} does not exist")

                # Delete the team from the database
                
                await connection.execute("DELETE FROM teams WHERE api_key = $1", api_key)
    
    async def get_team(self, api_key: str):
        async with self.pool.acquire() as connection:
            team = await connection.fetchrow("SELECT * FROM teams WHERE api_key = $1", api_key)
            if not team:
                return None
            return dict(team)
        

    ## Database Operations for Models
    async def add_model(self, model_name: str, provider: str, cost_per_input_token: float, cost_per_output_token: float):
        async with self.pool.acquire() as connection: 
            # Insert the new model into the database
            try:
                await connection.execute(
                    """
                    INSERT INTO models (name, provider, cost_per_input_token, cost_per_output_token)
                    VALUES ($1, $2, $3, $4)
                    """,
                    model_name, provider, cost_per_input_token, cost_per_output_token
                )
            except asyncpg.UniqueViolationError:
                raise ValueError(f"Model {model_name} already exists")
    
    async def update_model(self, model_name: str, **fields):
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
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                # Check if the model exists
                model = await connection.fetchrow("SELECT * FROM models WHERE name = $1", model_name)
                if not model:
                    raise ValueError(f"Model {model_name} does not exist")

                # Delete the model from the database
                await connection.execute("DELETE FROM models WHERE name = $1", model_name)

    
    async def get_model(self, model_name: str):
        async with self.pool.acquire() as connection:
            model = await connection.fetchrow("SELECT * FROM models WHERE name = $1", model_name)
            if not model:
                return None
            return dict(model)
        


# when using compose, set postgres rather than localhost, and use the password set in the docker-compose.yml file
db = Database(dsn=os.environ.get("DATABASE_URL", "postgresql://conduit:postgres_conduit@localhost:5432/conduit"))