"""
TDD Phase 0 — StateValueData Protocol + concrete value types.

Tests are written BEFORE the implementation in l3_features.py.
All tests here should fail (RED) until StateValueData and its
concrete classes are added to data_service/models/l3_features.py.

Run from data_service/ root:
    pytest tests/test_state_value_data.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ---------------------------------------------------------------------------
# Protocol import: must exist in l3_features
# ---------------------------------------------------------------------------

def test_state_value_data_protocol_is_importable():
    """StateValueData protocol must be defined in l3_features."""
    from models.l3_features import StateValueData  # noqa: F401


def test_concrete_types_are_importable():
    """All concrete implementations must be importable from l3_features."""
    from models.l3_features import (  # noqa: F401
        ScalarValue,
        VectorValue,
        LabelValue,
        FormationHistoryEntry,
        FormationHistoryValue,
    )


# ---------------------------------------------------------------------------
# ScalarValue — wraps a single float
# ---------------------------------------------------------------------------

class TestScalarValue:
    def setup_method(self):
        from models.l3_features import ScalarValue
        self.cls = ScalarValue

    def test_serialize_returns_float(self):
        sv = self.cls(value=3.14)
        result = sv.serialize()
        assert result == 3.14
        assert isinstance(result, float)

    def test_deserialize_round_trips(self):
        sv = self.cls(value=0.5)
        raw = sv.serialize()
        recovered = self.cls.deserialize(raw)
        assert isinstance(recovered, self.cls)
        assert recovered.value == pytest.approx(0.5)

    def test_zero_value_round_trips(self):
        sv = self.cls(value=0.0)
        assert self.cls.deserialize(sv.serialize()).value == 0.0

    def test_negative_value_round_trips(self):
        sv = self.cls(value=-12.7)
        assert self.cls.deserialize(sv.serialize()).value == pytest.approx(-12.7)


# ---------------------------------------------------------------------------
# VectorValue — wraps a list of floats (e.g. centroid, velocity)
# ---------------------------------------------------------------------------

class TestVectorValue:
    def setup_method(self):
        from models.l3_features import VectorValue
        self.cls = VectorValue

    def test_serialize_returns_list_of_floats(self):
        vv = self.cls(components=[1.0, 2.0, 3.0])
        result = vv.serialize()
        assert result == [1.0, 2.0, 3.0]
        assert isinstance(result, list)

    def test_deserialize_round_trips(self):
        vv = self.cls(components=[10.5, -3.2])
        raw = vv.serialize()
        recovered = self.cls.deserialize(raw)
        assert isinstance(recovered, self.cls)
        assert recovered.components == pytest.approx([10.5, -3.2])

    def test_empty_vector_round_trips(self):
        vv = self.cls(components=[])
        assert self.cls.deserialize(vv.serialize()).components == []

    def test_single_component_round_trips(self):
        vv = self.cls(components=[42.0])
        assert self.cls.deserialize(vv.serialize()).components == pytest.approx([42.0])


# ---------------------------------------------------------------------------
# LabelValue — wraps a categorical string + optional confidence float
# ---------------------------------------------------------------------------

class TestLabelValue:
    def setup_method(self):
        from models.l3_features import LabelValue
        self.cls = LabelValue

    def test_serialize_returns_dict_with_label(self):
        lv = self.cls(label="4-3-3", confidence=0.92)
        result = lv.serialize()
        assert isinstance(result, dict)
        assert result["label"] == "4-3-3"
        assert result["confidence"] == pytest.approx(0.92)

    def test_deserialize_round_trips(self):
        lv = self.cls(label="4-4-2", confidence=0.7)
        raw = lv.serialize()
        recovered = self.cls.deserialize(raw)
        assert isinstance(recovered, self.cls)
        assert recovered.label == "4-4-2"
        assert recovered.confidence == pytest.approx(0.7)

    def test_none_confidence_defaults_to_none(self):
        lv = self.cls(label="GK")
        result = lv.serialize()
        assert result["label"] == "GK"
        assert result.get("confidence") is None

    def test_label_round_trips_without_confidence(self):
        lv = self.cls(label="GK")
        raw = lv.serialize()
        recovered = self.cls.deserialize(raw)
        assert recovered.label == "GK"
        assert recovered.confidence is None


# ---------------------------------------------------------------------------
# FormationHistoryEntry — a single transition record
# ---------------------------------------------------------------------------

class TestFormationHistoryEntry:
    def setup_method(self):
        from models.l3_features import FormationHistoryEntry
        self.cls = FormationHistoryEntry

    def test_has_required_fields(self):
        entry = self.cls(label="4-3-3", timestamp_ms=90000, half="FIRST")
        assert entry.label == "4-3-3"
        assert entry.timestamp_ms == 90000
        assert entry.half == "FIRST"

    def test_serialises_to_dict(self):
        entry = self.cls(label="4-4-2", timestamp_ms=45000, half="SECOND")
        d = entry.to_dict()
        assert d["label"] == "4-4-2"
        assert d["timestamp_ms"] == 45000
        assert d["half"] == "SECOND"

    def test_from_dict_round_trips(self):
        entry = self.cls(label="3-5-2", timestamp_ms=12000, half="FIRST")
        recovered = self.cls.from_dict(entry.to_dict())
        assert recovered.label == entry.label
        assert recovered.timestamp_ms == entry.timestamp_ms
        assert recovered.half == entry.half


# ---------------------------------------------------------------------------
# FormationHistoryValue — list of FormationHistoryEntry
# ---------------------------------------------------------------------------

class TestFormationHistoryValue:
    def setup_method(self):
        from models.l3_features import FormationHistoryEntry, FormationHistoryValue
        self.entry_cls = FormationHistoryEntry
        self.cls = FormationHistoryValue

    def test_serialize_returns_list_of_dicts(self):
        entries = [
            self.entry_cls(label="4-3-3", timestamp_ms=0, half="FIRST"),
            self.entry_cls(label="4-4-2", timestamp_ms=45000, half="SECOND"),
        ]
        fhv = self.cls(entries=entries)
        result = fhv.serialize()
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["label"] == "4-3-3"
        assert result[1]["label"] == "4-4-2"

    def test_deserialize_round_trips(self):
        entries = [
            self.entry_cls(label="5-3-2", timestamp_ms=1000, half="FIRST"),
        ]
        fhv = self.cls(entries=entries)
        raw = fhv.serialize()
        recovered = self.cls.deserialize(raw)
        assert isinstance(recovered, self.cls)
        assert len(recovered.entries) == 1
        assert recovered.entries[0].label == "5-3-2"

    def test_empty_history_round_trips(self):
        fhv = self.cls(entries=[])
        raw = fhv.serialize()
        recovered = self.cls.deserialize(raw)
        assert recovered.entries == []


# ---------------------------------------------------------------------------
# StateValue — value field must accept all StateValueData concrete types
# ---------------------------------------------------------------------------

class TestStateValueAcceptsAllConcreteTypes:
    def setup_method(self):
        from models.l3_features import (
            StateValue, ScalarValue, VectorValue, LabelValue,
            FormationHistoryEntry, FormationHistoryValue,
        )
        self.StateValue = StateValue
        self.ScalarValue = ScalarValue
        self.VectorValue = VectorValue
        self.LabelValue = LabelValue
        self.FHE = FormationHistoryEntry
        self.FHV = FormationHistoryValue

    def test_state_value_accepts_scalar(self):
        sv = self.StateValue(
            feature_id=1,
            value=self.ScalarValue(value=0.5),
            last_updated_ts=0,
        )
        assert isinstance(sv.value, self.ScalarValue)

    def test_state_value_accepts_vector(self):
        sv = self.StateValue(
            feature_id=2,
            value=self.VectorValue(components=[1.0, 2.0]),
            last_updated_ts=0,
        )
        assert isinstance(sv.value, self.VectorValue)

    def test_state_value_accepts_label(self):
        sv = self.StateValue(
            feature_id=3,
            value=self.LabelValue(label="4-3-3"),
            last_updated_ts=0,
        )
        assert isinstance(sv.value, self.LabelValue)

    def test_state_value_accepts_formation_history(self):
        sv = self.StateValue(
            feature_id=4,
            value=self.FHV(entries=[]),
            last_updated_ts=0,
        )
        assert isinstance(sv.value, self.FHV)

    def test_state_value_no_longer_accepts_raw_float(self):
        """Assigning a bare float to StateValue.value should fail validation."""
        with pytest.raises(Exception):
            self.StateValue(
                feature_id=5,
                value=0.99,  # bare float — must now be rejected
                last_updated_ts=0,
            )


# ---------------------------------------------------------------------------
# Protocol structural check — all concrete types satisfy StateValueData
# ---------------------------------------------------------------------------

class TestStateValueDataProtocolCompliance:
    """Each concrete type must have serialize() and deserialize() as defined by the Protocol."""

    @pytest.mark.parametrize("cls_name,instance_factory,raw_factory", [
        ("ScalarValue",  lambda: __import__("models.l3_features", fromlist=["ScalarValue"]).ScalarValue(value=1.0),  lambda: 1.0),
        ("VectorValue",  lambda: __import__("models.l3_features", fromlist=["VectorValue"]).VectorValue(components=[1.0]),  lambda: [1.0]),
        ("LabelValue",   lambda: __import__("models.l3_features", fromlist=["LabelValue"]).LabelValue(label="x"),  lambda: {"label": "x", "confidence": None}),
    ])
    def test_has_serialize(self, cls_name, instance_factory, raw_factory):
        instance = instance_factory()
        assert hasattr(instance, "serialize"), f"{cls_name} must have serialize()"
        result = instance.serialize()
        assert result is not None

    @pytest.mark.parametrize("cls_name,instance_factory,raw_factory", [
        ("ScalarValue",  lambda: __import__("models.l3_features", fromlist=["ScalarValue"]).ScalarValue(value=1.0),  lambda: 1.0),
        ("VectorValue",  lambda: __import__("models.l3_features", fromlist=["VectorValue"]).VectorValue(components=[1.0]),  lambda: [1.0]),
        ("LabelValue",   lambda: __import__("models.l3_features", fromlist=["LabelValue"]).LabelValue(label="x"),  lambda: {"label": "x", "confidence": None}),
    ])
    def test_has_deserialize(self, cls_name, instance_factory, raw_factory):
        from models import l3_features as mod
        cls = getattr(mod, cls_name)
        assert hasattr(cls, "deserialize"), f"{cls_name} must have deserialize()"
