from typing import Optional
from pydantic import BaseModel
from .enums import Half, FeatureType, FeatureCategory, UpdateTrigger, PlayerRole


# ---- Registry (storage tier: YAML file, loaded at startup) ----
class FeatureDefinition(BaseModel):
    feature_id: int
    feature_name: str
    feature_description: str
    feature_type: FeatureType
    category: FeatureCategory
    unit: Optional[str] = None
    value_range: Optional[tuple[float, float]] = None
    update_trigger: Optional[UpdateTrigger] = None


# ---- Frame-wise buffer (storage tier: in-memory deque, per match_id) ----
class FeatureObservation(BaseModel):
    feature_id: int
    entity_id: Optional[int] = None
    value: float
    is_imputed: bool = False


class FrameFeatureRecord(BaseModel):
    frame_id: int
    match_id: str
    timestamp_ms: int
    half: Half
    observations: list[FeatureObservation] = []


# ---- Match state (storage tier: Redis — shared across L3 writer + L5 reader) ----
class StateValue(BaseModel):
    feature_id: int
    entity_id: Optional[int] = None
    value: float
    last_updated_ts: int


class MatchStateStore(BaseModel):
    """Read-only snapshot of one match's state, deserialized from Redis.
    Not a live view — does not stay in sync after construction.
    For reads/writes, use MatchStateRedisStore (storage/redis_store.py)."""
    match_id: str
    match_states: list[StateValue] = []
    team_states: list[StateValue] = []
    player_states: list[StateValue] = []


# ---- Pre-match info (storage tier: Postgres) ----
class SquadEntry(BaseModel):
    jersey_number: int
    entity_id: Optional[int] = None  # filled in via identity resolution during match
    role: PlayerRole
    is_starter: bool


class TeamInfo(BaseModel):
    team_id: int
    formation: str
    squad: list[SquadEntry] = []


class PreMatchInfo(BaseModel):
    match_id: str
    team_info: TeamInfo
    opponent_info: TeamInfo
