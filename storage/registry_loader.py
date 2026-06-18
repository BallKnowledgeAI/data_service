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
