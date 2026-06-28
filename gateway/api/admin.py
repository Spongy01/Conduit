from gateway.auth.admin import require_admin
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from gateway.core.model_catalog import add_model, update_model, delete_model
from gateway.core.team_config import create_team, update_team, revoke_team

# Admin API endpoint to add API keys, revoke them or update them

router = APIRouter()

class CreateTeamRequest(BaseModel):
    api_key: str
    team_id: str
    team_name: str
    allowed_models: list[str]
    rate_limit: int
    budget_limit: float
    budget_period: str = "monthly"

class UpdateTeamRequest(BaseModel):
    # All optional: send only the fields you want to change.
    team_name: str | None = None
    allowed_models: list[str] | None = None
    rate_limit: int | None = None
    budget_limit: float | None = None
    budget_period: str | None = None

class CreateModelRequest(BaseModel):
    model_name: str
    provider: str
    cost_per_input_token: float = 0.0
    cost_per_output_token: float = 0.0

######################################
#### Endpoints for Managing Teams ####
######################################

@router.post("/v1/teams", dependencies=[Depends(require_admin)])
async def create_team_endpoint(request: CreateTeamRequest):
    try:
        return await create_team(**request.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/v1/teams/{api_key}", dependencies=[Depends(require_admin)])
async def update_team_endpoint(api_key: str, request: UpdateTeamRequest):
    try:
        return await update_team(api_key, **request.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/v1/teams/{api_key}", dependencies=[Depends(require_admin)])
async def revoke_team_endpoint(api_key: str):
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
    try:
        return await add_model(**request.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/v1/models/{model_name}", dependencies=[Depends(require_admin)])
async def update_model_endpoint(model_name: str, request: CreateModelRequest):
    try:
        fields = request.model_dump(exclude_unset=True)
        fields.pop("model_name", None)
        return await update_model(model_name, **fields)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/v1/models/{model_name}", dependencies=[Depends(require_admin)])
async def delete_model_endpoint(model_name: str):
    try:
        await delete_model(model_name)
        return {"status": "deleted", "model_name": model_name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
