from __future__ import annotations

from typing import Any, Optional
from typing import runtime_checkable, Protocol
from pydantic import BaseModel, ConfigDict
from .enums import Half, FeatureType, FeatureCategory, UpdateTrigger, PlayerRole


# ---------------------------------------------------------------------------
# StateValueData — Protocol (structural interface) for all feature value types.
#
# Any class that implements serialize() / deserialize() satisfies this Protocol.
# Concrete implementations must live in this file (l3_features.py).
# ---------------------------------------------------------------------------

@runtime_checkable
class StateValueData(Protocol):
    """Structural interface for heterogeneous feature values stored in StateValue.

    All concrete implementations must provide:
      - serialize()   → JSON-serialisable primitive (float | list | dict)
      - deserialize() → classmethod; reconstructs instance from serialised form
    """

    def serialize(self) -> Any:
        """Return a JSON-serialisable representation of this value."""
        ...

    @classmethod
    def deserialize(cls, raw: Any) -> "StateValueData":
        """Reconstruct an instance from the JSON-deserialised form of serialize()."""
        ...


# ---------------------------------------------------------------------------
# ScalarValue — wraps a single float (e.g. speed, distance, ratio)
# ---------------------------------------------------------------------------

class ScalarValue(BaseModel):
    """Single numeric feature value (replaces bare float in legacy StateValue)."""

    value: float

    def serialize(self) -> float:
        return self.value

    @classmethod
    def deserialize(cls, raw: float) -> "ScalarValue":
        return cls(value=float(raw))


# ---------------------------------------------------------------------------
# VectorValue — wraps a fixed-length list of floats (e.g. centroid x/y, velocity)
# ---------------------------------------------------------------------------

class VectorValue(BaseModel):
    """Multi-dimensional numeric feature value."""

    components: list[float]

    def serialize(self) -> list[float]:
        return list(self.components)

    @classmethod
    def deserialize(cls, raw: list[float]) -> "VectorValue":
        return cls(components=[float(c) for c in raw])


# ---------------------------------------------------------------------------
# LabelValue — wraps a categorical string + optional confidence score
# ---------------------------------------------------------------------------

class LabelValue(BaseModel):
    """Categorical label with an optional confidence score.

    Examples: formation label ("4-3-3"), player role ("GK"), phase label.
    """

    label: str
    confidence: Optional[float] = None

    def serialize(self) -> dict[str, Any]:
        return {"label": self.label, "confidence": self.confidence}

    @classmethod
    def deserialize(cls, raw: dict[str, Any]) -> "LabelValue":
        return cls(label=raw["label"], confidence=raw.get("confidence"))


# ---------------------------------------------------------------------------
# FormationHistoryEntry — a single confirmed formation-transition record
# ---------------------------------------------------------------------------

class FormationHistoryEntry(BaseModel):
    """One confirmed formation transition event stored in match history."""

    label: str       # e.g. "4-3-3"
    timestamp_ms: int
    half: str        # "FIRST" | "SECOND"  (str to avoid circular import with Half enum)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "timestamp_ms": self.timestamp_ms,
            "half": self.half,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FormationHistoryEntry":
        return cls(label=d["label"], timestamp_ms=d["timestamp_ms"], half=d["half"])


# ---------------------------------------------------------------------------
# FormationHistoryValue — ordered list of FormationHistoryEntry (StateValueData)
# ---------------------------------------------------------------------------

class FormationHistoryValue(BaseModel):
    """Complete ordered formation-change history for one team in a match."""

    entries: list[FormationHistoryEntry] = []

    def serialize(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.entries]

    @classmethod
    def deserialize(cls, raw: list[dict[str, Any]]) -> "FormationHistoryValue":
        return cls(entries=[FormationHistoryEntry.from_dict(d) for d in raw])


# ---------------------------------------------------------------------------
# Helper union type — accepted as StateValue.value
# ---------------------------------------------------------------------------

StateValueData_T = ScalarValue | VectorValue | LabelValue | FormationHistoryValue


# ---------------------------------------------------------------------------
# Registry (storage tier: YAML file, loaded at startup)
# ---------------------------------------------------------------------------

class FeatureDefinition(BaseModel):
    feature_id: int
    feature_name: str
    feature_description: str
    feature_type: FeatureType
    category: FeatureCategory
    unit: Optional[str] = None
    value_range: Optional[tuple[float, float]] = None
    update_trigger: Optional[UpdateTrigger] = None


# ---------------------------------------------------------------------------
# Frame-wise buffer (storage tier: in-memory deque, per match_id)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Match state (storage tier: Redis — shared across L3 writer + L5 reader)
#
# BREAKING CHANGE: StateValue.value was `float`.
# It is now `StateValueData_T` (union of concrete StateValueData types).
# Downstream code that wrote bare floats must wrap them in ScalarValue(value=x).
# redis_store.py uses sv.value.serialize() instead of directly dumping sv.value.
# ---------------------------------------------------------------------------

class StateValue(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    feature_id: int
    entity_id: Optional[int] = None
    value: StateValueData_T   # changed from float → StateValueData_T
    last_updated_ts: int


class MatchStateStore(BaseModel):
    """Read-only snapshot of one match's state, deserialized from Redis.
    Not a live view — does not stay in sync after construction.
    For reads/writes, use MatchStateRedisStore (storage/redis_store.py)."""

    match_id: str
    match_states: list[StateValue] = []
    team_states: list[StateValue] = []
    player_states: list[StateValue] = []


# ---------------------------------------------------------------------------
# Pre-match info (storage tier: Postgres)
# ---------------------------------------------------------------------------

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
