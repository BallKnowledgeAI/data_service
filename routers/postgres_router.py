from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from pydantic import BaseModel
from storage.postgres_store import get_session_factory, upsert_identity_resolution, TeamInfoORM, SquadEntryORM
from config.settings import settings
from sqlalchemy.orm import Session

router = APIRouter(tags=["Postgres Data"])

session_factory = get_session_factory(settings.postgres_url)

def get_db():
    db = session_factory()
    try:
        yield db
    finally:
        db.close()

class TeamInfoCreate(BaseModel):
    team_id: int
    formation: str

class SquadEntryCreate(BaseModel):
    jersey_number: int
    entity_id: Optional[int] = None
    role: str
    is_starter: bool

class IdentityUpdate(BaseModel):
    entity_id: int

@router.post("/matches/{match_id}/teams")
def register_team(match_id: str, team: TeamInfoCreate, db: Session = Depends(get_db)):
    existing = db.query(TeamInfoORM).filter_by(match_id=match_id, team_id=team.team_id).first()
    if existing:
        return {"status": "already_exists", "id": existing.id}
    
    new_team = TeamInfoORM(
        match_id=match_id,
        team_id=team.team_id,
        formation=team.formation
    )
    db.add(new_team)
    db.commit()
    db.refresh(new_team)
    return {"status": "created", "id": new_team.id}

@router.post("/matches/{match_id}/teams/{team_id}/squad")
def register_squad_entry(match_id: str, team_id: int, entry: SquadEntryCreate, db: Session = Depends(get_db)):
    team = db.query(TeamInfoORM).filter_by(match_id=match_id, team_id=team_id).first()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found for this match")
        
    existing = db.query(SquadEntryORM).filter_by(team_info_id=team.id, jersey_number=entry.jersey_number).first()
    if existing:
        return {"status": "already_exists"}
        
    new_entry = SquadEntryORM(
        team_info_id=team.id,
        jersey_number=entry.jersey_number,
        entity_id=entry.entity_id,
        role=entry.role,
        is_starter=entry.is_starter
    )
    db.add(new_entry)
    db.commit()
    return {"status": "created"}

@router.patch("/matches/{match_id}/teams/{team_id}/squad/{jersey_number}/identity")
def update_identity(match_id: str, team_id: int, jersey_number: int, identity: IdentityUpdate):
    try:
        upsert_identity_resolution(session_factory, match_id, team_id, jersey_number, identity.entity_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success"}
