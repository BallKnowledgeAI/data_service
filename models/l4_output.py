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
