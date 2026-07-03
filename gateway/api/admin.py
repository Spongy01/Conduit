"""Admin API: create/update/revoke teams and manage the model catalog.
Every endpoint here is gated by require_admin (a single shared admin key),
unlike the chat API which authenticates per-team."""
from gateway.auth.admin import require_admin
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from gateway.core.model_catalog import add_model, update_model, delete_model
from gateway.core.team_config import create_team, update_team, revoke_team

# Admin API endpoint to add API keys, revoke them or update them

router = APIRouter()

class CreateTeamRequest(BaseModel):
    """Body for POST /v1/teams: registers a new team and its API key."""
    api_key: str
    team_id: str
    team_name: str
    allowed_models: list[str]
    rate_limit: int
    budget_limit: float
    budget_period: str = "monthly"

class UpdateTeamRequest(BaseModel):
    """Body for PATCH /v1/teams/{api_key}. All optional: send only the
    fields you want to change."""
    team_name: str | None = None
    allowed_models: list[str] | None = None
    rate_limit: int | None = None
    budget_limit: float | None = None
    budget_period: str | None = None

class CreateModelRequest(BaseModel):
    """Body for POST/PATCH /v1/models: registers or updates a model's
    provider and per-token pricing used for budget estimation."""
    model_name: str
    provider: str
    cost_per_input_token: float = 0.0
    cost_per_output_token: float = 0.0

######################################
#### Endpoints for Managing Teams ####
######################################

@router.post("/v1/teams", dependencies=[Depends(require_admin)])
async def create_team_endpoint(request: CreateTeamRequest):
    """Registers a new team. Returns 400 if the api_key is already taken."""
    try:
        return await create_team(**request.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/v1/teams/{api_key}", dependencies=[Depends(require_admin)])
async def update_team_endpoint(api_key: str, request: UpdateTeamRequest):
    """Updates only the fields present in the request body (exclude_unset),
    so omitted fields keep their existing values. 404 if the team is unknown."""
    try:
        return await update_team(api_key, **request.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/v1/teams/{api_key}", dependencies=[Depends(require_admin)])
async def revoke_team_endpoint(api_key: str):
    """Deletes a team's config, invalidating its API key immediately."""
    try:
        await revoke_team(api_key)
        return {"status": "revoked", "api_key": api_key}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


#####################################
### Endpoints for Managing Models ###
#####################################

@router.post("/v1/models", dependencies=[Depends(require_admin)])
async def create_model_endpoint(request: CreateModelRequest):
    """Adds a new model to the catalog. Returns 400 if it already exists."""
    try:
        return await add_model(**request.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/v1/models/{model_name}", dependencies=[Depends(require_admin)])
async def update_model_endpoint(model_name: str, request: CreateModelRequest):
    """Updates a model's provider/pricing fields. model_name is the path
    param, not a mutable field, so it's dropped from the update payload."""
    try:
        fields = request.model_dump(exclude_unset=True)
        fields.pop("model_name", None)
        return await update_model(model_name, **fields)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/v1/models/{model_name}", dependencies=[Depends(require_admin)])
async def delete_model_endpoint(model_name: str):
    """Removes a model from the catalog. 404 if it doesn't exist."""
    try:
        await delete_model(model_name)
        return {"status": "deleted", "model_name": model_name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
