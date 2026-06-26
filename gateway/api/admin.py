from gateway.auth.admin import require_admin
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from gateway.core.team_config import create_team, update_team, get_team_config, revoke_team
# Admin API endpoint to add API keys, revoke them or update them

router = APIRouter()

class CreateTeamRequest(BaseModel):
    api_key: str
    allowed_models: list[dict]  # List of dicts with 'name' and 'provider' keys
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

@router.post("v1/teams", dependencies=[Depends(require_admin)])
def create_team(request: CreateTeamRequest):
    try:
        return create_team(**request.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
       

@router.patch("v1/teams/{api_key}", dependencies=[Depends(require_admin)])
def update_team(api_key: str, request: UpdateTeamRequest):
    try:
        return update_team(api_key, **request.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
 
@router.delete("v1/teams/{api_key}", dependencies=[Depends(require_admin)])
def revoke_team_endpoint(api_key: str):
    try:
        revoke_team(api_key)
        return {"status": "revoked", "api_key": api_key}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))