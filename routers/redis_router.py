from fastapi import APIRouter, Depends
from typing import List, Optional
from models.l3_features import StateValue
from storage.redis_store import MatchStateRedisStore
from config.settings import settings

router = APIRouter(tags=["Redis State"])

def get_redis_store():
    # redis-py handles connection pooling internally
    store = MatchStateRedisStore(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_auth,
    )
    try:
        yield store
    finally:
        pass

@router.post("/matches/{match_id}/state/{scope}")
def set_match_state(match_id: str, scope: str, sv: StateValue, store: MatchStateRedisStore = Depends(get_redis_store)):
    store.set_state(match_id, scope, sv)
    return {"status": "success"}

@router.get("/matches/{match_id}/state/{scope}", response_model=List[StateValue])
def get_match_state(match_id: str, scope: str, store: MatchStateRedisStore = Depends(get_redis_store)):
    return store.get_all(match_id, scope)

@router.post("/matches/{match_id}/series/{scope}")
def append_state_series(match_id: str, scope: str, sv: StateValue, store: MatchStateRedisStore = Depends(get_redis_store)):
    store.append_state_series(match_id, scope, sv)
    return {"status": "success"}

@router.get("/matches/{match_id}/series/{scope}", response_model=List[StateValue])
def get_state_series(match_id: str, scope: str, feature_id: int, entity_id: Optional[int] = None, store: MatchStateRedisStore = Depends(get_redis_store)):
    return store.get_state_series(match_id, scope, feature_id, entity_id)

@router.delete("/matches/{match_id}")
def release_match(match_id: str, store: MatchStateRedisStore = Depends(get_redis_store)):
    store.release_match(match_id)
    return {"status": "success"}
