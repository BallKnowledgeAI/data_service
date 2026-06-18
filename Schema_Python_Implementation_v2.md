# Tactical Analysis Pipeline — Python Implementation Guide

> Scope: Pydantic models for all schema objects (L1–L4 + Auth), mapped to their storage tier (in-memory / Redis / Postgres / YAML), with concrete code for each.
>
> Excludes: deployment/multi-tenancy objects (`PipelineInstance`, `MatchSession` scheduling) — tracked separately.

---

## 1. Project layout

```
schema_design/
├── models/
│   ├── __init__.py
│   ├── enums.py            # all enums
│   ├── l1_ingestion.py      # RawFrame
│   ├── l2_l3_bridge.py      # DataEvent
│   ├── l3_features.py       # FeatureDefinition, FrameFeatureRecord, FeatureObservation,
│   │                         # MatchStateStore, StateValue, PreMatchInfo, TeamInfo, SquadEntry
│   ├── l4_output.py         # SequenceModelOutput, OutputMeta, ShapFeature,
│   │                         # Anomaly, Score, StrategyCall
│   └── auth.py               # Organization, User, RefreshToken
├── storage/
│   ├── __init__.py
│   ├── memory_store.py       # in-process buffers (deque, dict)
│   ├── redis_store.py        # MatchStateStore client
│   ├── postgres_store.py     # SQLAlchemy models + session for PreMatchInfo, Auth, identity resolution
│   └── registry_loader.py    # YAML -> FeatureDefinition[] loader
├── config/
│   └── feature_registry.yaml
└── requirements.txt
```

```txt
# requirements.txt
pydantic>=2.0
redis>=5.0
sqlalchemy>=2.0
psycopg2-binary
pyyaml
```

---

## 2. Enums (`models/enums.py`)

```python
from enum import Enum


class Half(str, Enum):
    FIRST = "FIRST"
    SECOND = "SECOND"
    # v1 scope: EXTRA_TIME and PENALTIES intentionally excluded.
    # Add in a future version when cup/knockout match support is required.


class CVEntityType(str, Enum):
    PLAYER = "PLAYER"
    REFEREE = "REFEREE"
    BALL = "BALL"


class PlayerRole(str, Enum):
    GK = "GK"
    OUTFIELD = "OUTFIELD"


class EventType(str, Enum):
    # Positional
    PLAYER_POSITION = "PLAYER_POSITION"
    BALL_POSITION = "BALL_POSITION"
    # Ball events
    PASS = "PASS"
    SHOT = "SHOT"
    DRIBBLE = "DRIBBLE"
    CLEARANCE = "CLEARANCE"
    INTERCEPTION = "INTERCEPTION"
    TACKLE = "TACKLE"
    # Spatial
    PRESSURE = "PRESSURE"
    CARRY = "CARRY"
    OFFSIDE_LINE = "OFFSIDE_LINE"
    PRESSURE_ZONE = "PRESSURE_ZONE"
    # Match lifecycle
    MATCH_START = "MATCH_START"
    MATCH_END = "MATCH_END"
    HALF_START = "HALF_START"
    HALF_END = "HALF_END"
    SUBSTITUTION = "SUBSTITUTION"
    FORMATION_CHANGE = "FORMATION_CHANGE"
    # System
    SOURCE_CONNECTED = "SOURCE_CONNECTED"
    SOURCE_DISCONNECTED = "SOURCE_DISCONNECTED"
    REPLAY_COMPLETE = "REPLAY_COMPLETE"


class FeatureType(str, Enum):
    FRAME_WISE = "FRAME_WISE"
    MATCH_STATE = "MATCH_STATE"


class FeatureCategory(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    TEAM = "TEAM"
    MATCH = "MATCH"


class UpdateTrigger(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    EVENT_DRIVEN = "EVENT_DRIVEN"


class EntityType(str, Enum):
    PLAYER = "PLAYER"
    TEAM = "TEAM"


class AnomalyType(str, Enum):
    PRESSING_TRIGGER = "PRESSING_TRIGGER"
    COUNTER_ATTACK_LAUNCH = "COUNTER_ATTACK_LAUNCH"
    OVERLOAD_ZONE = "OVERLOAD_ZONE"
    DEFENSIVE_LINE_BREAK = "DEFENSIVE_LINE_BREAK"
    SHAPE_DISRUPTION = "SHAPE_DISRUPTION"
    FATIGUE_SIGNATURE = "FATIGUE_SIGNATURE"
    HIGH_DANGER_BUILDUP = "HIGH_DANGER_BUILDUP"
    DEAD_BALL_OPPORTUNITY = "DEAD_BALL_OPPORTUNITY"


class ScoreType(str, Enum):
    THREAT_PROBABILITY = "THREAT_PROBABILITY"
    PRESS_SUCCESS_PROBABILITY = "PRESS_SUCCESS_PROBABILITY"
    THROUGH_BALL_VIABILITY = "THROUGH_BALL_VIABILITY"
    TACTICAL_STABILITY = "TACTICAL_STABILITY"
    TRANSITION_EXPOSURE = "TRANSITION_EXPOSURE"
    SET_PIECE_THREAT = "SET_PIECE_THREAT"
    FATIGUE_INDEX = "FATIGUE_INDEX"
    OPPONENT_PREDICTABILITY = "OPPONENT_PREDICTABILITY"


class CallType(str, Enum):
    SUBSTITUTION = "SUBSTITUTION"
    SHAPE_CHANGE = "SHAPE_CHANGE"
    PRESSING_INSTRUCTION = "PRESSING_INSTRUCTION"
    DROP_BLOCK = "DROP_BLOCK"
    WIDTH_ADJUSTMENT = "WIDTH_ADJUSTMENT"
    DEFENSIVE_LINE_HEIGHT = "DEFENSIVE_LINE_HEIGHT"
    EXPLOIT_FLAG = "EXPLOIT_FLAG"
    VULNERABILITY_FLAG = "VULNERABILITY_FLAG"


class Urgency(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    NEXT_DEAD_BALL = "NEXT_DEAD_BALL"
    ADVISORY = "ADVISORY"


class LicenseTier(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TRIAL = "TRIAL"


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    HEAD_COACH = "HEAD_COACH"
    ASSISTANT_COACH = "ASSISTANT_COACH"
    ANALYST = "ANALYST"
    VIDEO_OPERATOR = "VIDEO_OPERATOR"
```

---

## 3. Layer 1 — `RawFrame` (`models/l1_ingestion.py`)

**Storage tier: in-memory only** — bounded `deque`, drop-oldest (tentative — see note in guide below).

```python
from pydantic import BaseModel
from .enums import Half


class RawFrame(BaseModel):
    frame_id: int
    timestamp: float
    data: bytes
    half: Half
```

---

## 4. L2→L3 Bridge — `DataEvent` (`models/l2_l3_bridge.py`)

**Storage tier: in-memory (streamed)**, not persisted (archiving deferred per current decision).

`payload`/`metadata` remain untyped `dict` for now — flagged as tentative, not final.

```python
from typing import Any, Optional
from pydantic import BaseModel
from .enums import Half, EventType


class DataEvent(BaseModel):
    sequence_number: int
    timestamp_ms: int
    half: Half
    source_id: str
    event_type: EventType
    match_id: str
    confidence: float

    # NOTE: untyped "for now" — CV-origin events currently encode DetectedEntity
    # fields (entity_id, entity_type, team, jersey_number, role, position_m,
    # confidences) inside this dict. No top-level entity_id on the envelope at
    # present, so routing/identity-resolution requires parsing this payload.
    payload: dict[str, Any]
    metadata: dict[str, Any] = {}
```

---

## 5. Layer 3 — Feature Engineering (`models/l3_features.py`)

```python
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
```

---

## 6. Layer 4 — Sequence Model Output (`models/l4_output.py`)

**Storage tier: in-memory, pushed live to L5** — not persisted (archiving deferred).

```python
from typing import Optional
from pydantic import BaseModel
from .enums import EntityType, AnomalyType, ScoreType, CallType, Urgency


class ShapFeature(BaseModel):
    feature_id: int
    shap_value: float
    feature_value: float


class Anomaly(BaseModel):
    anomaly_type: AnomalyType
    entity_type: EntityType
    entity_id: int
    confidence: float
    shap_features: list[ShapFeature] = []


class Score(BaseModel):
    score_type: ScoreType
    entity_type: EntityType
    entity_id: int
    value: float
    confidence: float
    shap_features: list[ShapFeature] = []


class CallParameters(BaseModel):
    """Placeholder base — variant subclasses per CallType deferred pending CallType prioritization.
    When implementing, use a discriminated union keyed on `call_type`:
        parameters: Annotated[
            Union[SubstitutionParameters, ShapeChangeParameters, ...],
            Field(discriminator="call_type")
        ]
    Each subclass should carry a Literal[CallType.X] `call_type` field as the discriminator key."""
    pass


class StrategyCall(BaseModel):
    call_type: CallType
    urgency: Urgency
    # entity_type and entity_id are NULL for team-level calls
    # (SHAPE_CHANGE, DROP_BLOCK, WIDTH_ADJUSTMENT, DEFENSIVE_LINE_HEIGHT).
    # Populated for player-level calls (SUBSTITUTION, EXPLOIT_FLAG, VULNERABILITY_FLAG, etc.).
    entity_type: Optional[EntityType] = None
    entity_id: Optional[int] = None
    confidence: float
    parameters: CallParameters
    shap_features: list[ShapFeature] = []


class OutputMeta(BaseModel):
    window_start_ts: float
    window_end_ts: float
    window_size: int
    model_version: str


class SequenceModelOutput(BaseModel):
    inference_id: str
    match_id: str
    timestamp: float
    anomalies: list[Anomaly] = []
    scores: list[Score] = []
    strategy_calls: list[StrategyCall] = []
    meta: OutputMeta
```

---

## 7. Auth (`models/auth.py`)

**Storage tier: Postgres** — relational, durable, queried on every auth check.

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from .enums import LicenseTier, LicenseStatus, UserRole


class Organization(BaseModel):
    org_id: str
    org_name: str
    license_tier: LicenseTier
    license_status: LicenseStatus
    license_expiry: datetime
    created_at: datetime


class User(BaseModel):
    user_id: str
    org_id: str
    username: str
    email: str
    password_hash: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None


class RefreshToken(BaseModel):
    token_id: str
    user_id: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool
```

---

## 8. Storage layer implementations

### 8.1 In-memory store (`storage/memory_store.py`)

Covers `RawFrame` buffer, `FrameFeatureRecord` deque, `DataEvent` stream handling — all per-`match_id`, process-local.

```python
from collections import deque
from threading import Lock
from models.l1_ingestion import RawFrame
from models.l3_features import FrameFeatureRecord


class RawFrameBuffer:
    """Bounded queue, drop-oldest policy.

    NOTE: drop-oldest is a tentative choice addressing the CV-layer throughput
    bottleneck — not finalized. Alternatives under consideration: drop-newest,
    fixed-interval downsampling, disk-backed overflow, adaptive backpressure,
    dynamic resolution reduction. Revisit once CV throughput is benchmarked.
    """

    def __init__(self, maxlen: int):
        self._buf: deque[RawFrame] = deque(maxlen=maxlen)
        self._lock = Lock()

    def push(self, frame: RawFrame) -> None:
        with self._lock:
            self._buf.append(frame)  # deque(maxlen=N) auto-drops oldest on overflow

    def pop(self) -> RawFrame | None:
        with self._lock:
            return self._buf.popleft() if self._buf else None

    def __len__(self) -> int:
        return len(self._buf)


class FrameFeatureBuffer:
    """Per-match_id deque of FrameFeatureRecord, window size W."""

    def __init__(self, window_size: int):
        self._window_size = window_size
        self._buffers: dict[str, deque[FrameFeatureRecord]] = {}
        self._lock = Lock()

    def _get_or_create(self, match_id: str) -> deque[FrameFeatureRecord]:
        if match_id not in self._buffers:
            self._buffers[match_id] = deque(maxlen=self._window_size)
        return self._buffers[match_id]

    def push(self, record: FrameFeatureRecord) -> None:
        with self._lock:
            self._get_or_create(record.match_id).append(record)

    def get_window(self, match_id: str) -> list[FrameFeatureRecord]:
        with self._lock:
            return list(self._buffers.get(match_id, []))

    def release(self, match_id: str) -> None:
        """Call on match end to free memory — see cleanup note in storage guide."""
        with self._lock:
            self._buffers.pop(match_id, None)
```

### 8.2 Redis store — `MatchStateStore` (`storage/redis_store.py`)

Shared across L3 (writer) and L5 (reader), potentially on different VMs.

```python
import json
import time
import redis
from models.l3_features import StateValue

SCOPE_MATCH = "match"
SCOPE_TEAM = "team"
SCOPE_PLAYER = "player"


class MatchStateRedisStore:
    def __init__(self, host: str, port: int = 6379, password: str | None = None, ttl_seconds: int = 4 * 3600):
        self._r = redis.Redis(host=host, port=port, password=password, decode_responses=True)
        self._ttl = ttl_seconds  # backstop cleanup in case explicit DEL on match-end is missed

    @staticmethod
    def _key(match_id: str, scope: str) -> str:
        return f"matchstate:{match_id}:{scope}"

    @staticmethod
    def _field(feature_id: int, entity_id: int | None) -> str:
        return f"{feature_id}:{entity_id if entity_id is not None else ''}"

    def set_state(self, match_id: str, scope: str, sv: StateValue) -> None:
        key = self._key(match_id, scope)
        field = self._field(sv.feature_id, sv.entity_id)
        value = json.dumps({"value": sv.value, "last_updated_ts": sv.last_updated_ts})
        pipe = self._r.pipeline()
        pipe.hset(key, field, value)
        pipe.expire(key, self._ttl)
        pipe.execute()

    def get_all(self, match_id: str, scope: str) -> list[StateValue]:
        key = self._key(match_id, scope)
        raw = self._r.hgetall(key)
        result = []
        for field, value in raw.items():
            feature_id_str, entity_id_str = field.split(":")
            parsed = json.loads(value)
            result.append(StateValue(
                feature_id=int(feature_id_str),
                entity_id=int(entity_id_str) if entity_id_str else None,
                value=parsed["value"],
                last_updated_ts=parsed["last_updated_ts"],
            ))
        return result

    def release_match(self, match_id: str) -> None:
        """Call on match end — explicit cleanup; TTL is the backstop."""
        for scope in (SCOPE_MATCH, SCOPE_TEAM, SCOPE_PLAYER):
            self._r.delete(self._key(match_id, scope))


# Usage:
# store = MatchStateRedisStore(host="10.0.0.5")
# store.set_state(match_id, SCOPE_TEAM, StateValue(feature_id=12, entity_id=1, value=0.63, last_updated_ts=int(time.time())))
# team_states = store.get_all(match_id, SCOPE_TEAM)
```

### 8.3 Postgres store (`storage/postgres_store.py`)

Covers `PreMatchInfo`/`TeamInfo`/`SquadEntry`, `Organization`/`User`/`RefreshToken`, and the async identity-resolution write-back.

```python
from sqlalchemy import create_engine, Column, String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.dialects.postgresql import insert as pg_insert

Base = declarative_base()


class OrganizationORM(Base):
    __tablename__ = "organizations"
    org_id = Column(String, primary_key=True)
    org_name = Column(String, nullable=False)
    license_tier = Column(String, nullable=False)
    license_status = Column(String, nullable=False)
    license_expiry = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False)


class UserORM(Base):
    __tablename__ = "users"
    user_id = Column(String, primary_key=True)
    org_id = Column(String, ForeignKey("organizations.org_id"), nullable=False)
    username = Column(String, nullable=False)
    email = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False)
    last_login = Column(DateTime, nullable=True)


class RefreshTokenORM(Base):
    __tablename__ = "refresh_tokens"
    token_id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False)
    token_hash = Column(String, nullable=False)
    issued_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, nullable=False, default=False)


class TeamInfoORM(Base):
    __tablename__ = "team_info"
    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)  # "self" | "opponent"
    team_id = Column(Integer, nullable=False)
    formation = Column(String, nullable=False)
    squad = relationship("SquadEntryORM", back_populates="team", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("match_id", "side", name="uq_match_side"),)


class SquadEntryORM(Base):
    __tablename__ = "squad_entries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    team_info_id = Column(Integer, ForeignKey("team_info.id"), nullable=False)
    jersey_number = Column(Integer, nullable=False)
    entity_id = Column(Integer, nullable=True)  # filled by identity resolution
    role = Column(String, nullable=False)
    is_starter = Column(Boolean, nullable=False)
    team = relationship("TeamInfoORM", back_populates="squad")
    __table_args__ = (UniqueConstraint("team_info_id", "jersey_number", name="uq_team_jersey"),)


def get_session_factory(db_url: str):
    engine = create_engine(db_url, pool_size=10, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def upsert_identity_resolution(session_factory, match_id: str, side: str, jersey_number: int, entity_id: int) -> None:
    """Fire-and-forget, async-callable. Idempotent UPSERT keyed on (team_info_id, jersey_number).
    Safe to call concurrently — on conflict, overwrites entity_id in place.
    Call this off the hot path (e.g. via a background task queue) — does not block pipeline progress."""
    session = session_factory()
    try:
        team = session.query(TeamInfoORM).filter_by(match_id=match_id, side=side).one()
        stmt = (
            pg_insert(SquadEntryORM)
            .values(team_info_id=team.id, jersey_number=jersey_number, entity_id=entity_id)
            .on_conflict_do_update(
                constraint="uq_team_jersey",
                set_={"entity_id": entity_id},
            )
        )
        session.execute(stmt)
        session.commit()
    finally:
        session.close()
```

### 8.4 Feature registry loader (`storage/registry_loader.py`)

```python
import yaml
from models.l3_features import FeatureDefinition


def load_feature_registry(path: str) -> dict[int, FeatureDefinition]:
    """Loaded once at pipeline startup. Validated by Pydantic on load — fails fast
    on malformed config rather than at runtime."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    definitions = [FeatureDefinition(**item) for item in raw["features"]]
    # feature_id is the ordering contract for the sequence model input vector —
    # enforce uniqueness here.
    by_id = {}
    for d in definitions:
        if d.feature_id in by_id:
            raise ValueError(f"Duplicate feature_id {d.feature_id} in registry")
        by_id[d.feature_id] = d
    return by_id
```

```yaml
# config/feature_registry.yaml
features:
  - feature_id: 1
    feature_name: player_speed
    feature_description: "Instantaneous player speed in m/s"
    feature_type: FRAME_WISE
    category: INDIVIDUAL
    unit: "m/s"
    value_range: [0.0, 12.0]
  - feature_id: 2
    feature_name: team_possession_pct
    feature_description: "Rolling possession percentage for a team"
    feature_type: MATCH_STATE
    category: TEAM
    unit: "ratio"
    value_range: [0.0, 1.0]
    update_trigger: CONTINUOUS
```

---

## 9. Storage tier summary

| Object | Tier | Module |
| --- | --- | --- |
| `RawFrame` | In-memory (bounded deque, drop-oldest — tentative) | `storage/memory_store.py` |
| `DataEvent` | In-memory (streamed, not persisted) | n/a — passed directly between L2/L3 via queue/pub-sub |
| `FeatureDefinition` | YAML (loaded at startup) | `storage/registry_loader.py` |
| `FrameFeatureRecord` / `FeatureObservation` | In-memory (deque, per `match_id`) | `storage/memory_store.py` |
| `MatchStateStore` / `StateValue` | **Redis** (shared — L3 writer, L5 reader) | `storage/redis_store.py` |
| `PreMatchInfo` / `TeamInfo` / `SquadEntry` | **Postgres** | `storage/postgres_store.py` |
| `SequenceModelOutput` (+ children) | In-memory, pushed live (not persisted) | n/a — pushed directly to L5 |
| `Organization` / `User` / `RefreshToken` | **Postgres** | `storage/postgres_store.py` |

---

## 10. Open items carried into implementation

- `DataEvent.payload` / `metadata` are untyped `dict` — typed `PayloadModel` variants deferred, not yet implemented.
- `RawFrameBuffer` drop-oldest policy is tentative pending CV throughput benchmarking — alternatives documented in code comment.
- `StrategyCall.parameters` (`CallParameters`) is a placeholder base class — variant subclasses per `CallType` deferred pending consultant input. When implementing, use a Pydantic v2 discriminated union keyed on `call_type` (discriminator field name already aligns with the enum).
- `DataEvent`/`SequenceModelOutput` archiving to Parquet/HDF5 (training data, post-match review) is not implemented — current decision is no archiving.
- Redis/Postgres connection details (host, credentials, TLS) are environment-specific — not hardcoded in the modules above; inject via config/env vars at deployment time.
- `Half` enum covers FIRST/SECOND only — EXTRA_TIME and PENALTIES are out of scope for v1. Extend when cup/knockout match support is required.
