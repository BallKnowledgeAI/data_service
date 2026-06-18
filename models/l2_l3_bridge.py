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
