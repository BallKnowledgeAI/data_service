"""
Test suite for the Tactical Analysis Pipeline schema implementation.
Covers: Pydantic models (all layers), memory store, and feature registry loader.
Skips: Redis and Postgres (require live external services).
"""

import sys
import os
import traceback
from datetime import datetime, timezone

# Ensure the project root is on sys.path so models/ and storage/ are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Also change working directory to project root so relative YAML paths work
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def assert_values(enum_cls, expected):
    actual = {e.value for e in enum_cls}
    for v in expected:
        assert v in actual, f"Missing value {v!r} in {enum_cls.__name__}"


def assert_len(enum_cls, n):
    actual = len(list(enum_cls))
    assert actual == n, f"{enum_cls.__name__} has {actual} members, expected {n}"


def test(name, fn):
    try:
        fn()
        print(f"  {PASS} {name}")
        results.append((name, True, None))
    except Exception as e:
        print(f"  {FAIL} {name}")
        print(f"       {e}")
        results.append((name, False, traceback.format_exc()))


# ---------------------------------------------------------------------------
# 1. Enums
# ---------------------------------------------------------------------------
print("\n[1] Enums")

from models.enums import (
    Half, CVEntityType, PlayerRole, EventType, FeatureType, FeatureCategory,
    UpdateTrigger, EntityType, AnomalyType, ScoreType, CallType, Urgency,
    LicenseTier, LicenseStatus, UserRole,
)

test("Half values",          lambda: assert_values(Half, ["FIRST", "SECOND"]))
test("CVEntityType values",  lambda: assert_values(CVEntityType, ["PLAYER", "REFEREE", "BALL"]))
test("PlayerRole values",    lambda: assert_values(PlayerRole, ["GK", "OUTFIELD"]))
test("AnomalyType count",    lambda: assert_len(AnomalyType, 8))
test("ScoreType count",      lambda: assert_len(ScoreType, 8))
test("CallType count",       lambda: assert_len(CallType, 8))
test("Urgency values",       lambda: assert_values(Urgency, ["IMMEDIATE", "NEXT_DEAD_BALL", "ADVISORY"]))
test("LicenseTier values",   lambda: assert_values(LicenseTier, ["BASIC", "PRO", "ENTERPRISE"]))
test("LicenseStatus values", lambda: assert_values(LicenseStatus, ["ACTIVE", "SUSPENDED", "EXPIRED", "TRIAL"]))
test("UserRole count",       lambda: assert_len(UserRole, 5))
test("EventType count",      lambda: assert_len(EventType, 21))





# ---------------------------------------------------------------------------
# 2. RawFrame (L1)
# ---------------------------------------------------------------------------
print("\n[2] RawFrame (L1)")

from models.l1_ingestion import RawFrame

def _raw_frame():
    f = RawFrame(frame_id=1, timestamp=1234.5, data=b"\x00\x01\x02", half=Half.FIRST)
    assert f.frame_id == 1
    assert f.half == Half.FIRST
    assert isinstance(f.data, bytes)

test("RawFrame instantiation", _raw_frame)

def _raw_frame_bad_half():
    try:
        RawFrame(frame_id=1, timestamp=0.0, data=b"", half="THIRD")
        raise AssertionError("Should have raised ValidationError")
    except Exception as e:
        assert "THIRD" in str(e) or "validation" in str(e).lower()

test("RawFrame rejects invalid half", _raw_frame_bad_half)


# ---------------------------------------------------------------------------
# 3. DataEvent (L2->L3)
# ---------------------------------------------------------------------------
print("\n[3] DataEvent (L2->L3)")

from models.l2_l3_bridge import DataEvent

def _data_event():
    e = DataEvent(
        sequence_number=42,
        timestamp_ms=1_000_000,
        half=Half.SECOND,
        source_id="cam-01",
        event_type=EventType.PASS,
        match_id="match-abc",
        confidence=0.95,
        payload={"entity_id": 7, "position_m": [50.1, 34.2]},
        metadata={"latency_ms": 3},
    )
    assert e.event_type == EventType.PASS
    assert e.payload["entity_id"] == 7
    assert e.metadata["latency_ms"] == 3

test("DataEvent instantiation", _data_event)

def _data_event_empty_metadata():
    e = DataEvent(
        sequence_number=1, timestamp_ms=0, half=Half.FIRST,
        source_id="s", event_type=EventType.BALL_POSITION,
        match_id="m", confidence=1.0, payload={},
    )
    assert e.metadata == {}

test("DataEvent metadata defaults to {}", _data_event_empty_metadata)


# ---------------------------------------------------------------------------
# 4. L3 Feature models
# ---------------------------------------------------------------------------
print("\n[4] L3 Feature models")

from models.l3_features import (
    FeatureDefinition, FeatureObservation, FrameFeatureRecord,
    StateValue, MatchStateStore, SquadEntry, TeamInfo, PreMatchInfo,
)

def _feature_definition():
    fd = FeatureDefinition(
        feature_id=1,
        feature_name="player_speed",
        feature_description="Speed in m/s",
        feature_type=FeatureType.FRAME_WISE,
        category=FeatureCategory.INDIVIDUAL,
        unit="m/s",
        value_range=(0.0, 12.0),
    )
    assert fd.update_trigger is None  # optional, not set
    assert fd.value_range == (0.0, 12.0)

test("FeatureDefinition instantiation", _feature_definition)

def _feature_observation():
    obs = FeatureObservation(feature_id=1, entity_id=99, value=8.5)
    assert not obs.is_imputed
    obs2 = FeatureObservation(feature_id=2, value=0.6, is_imputed=True)
    assert obs2.entity_id is None

test("FeatureObservation instantiation + defaults", _feature_observation)

def _frame_feature_record():
    obs = FeatureObservation(feature_id=1, entity_id=5, value=3.2)
    rec = FrameFeatureRecord(
        frame_id=10, match_id="match-1", timestamp_ms=5000,
        half=Half.FIRST, observations=[obs],
    )
    assert len(rec.observations) == 1
    assert rec.observations[0].value == 3.2

test("FrameFeatureRecord instantiation", _frame_feature_record)

def _state_value():
    sv = StateValue(feature_id=2, entity_id=1, value=0.63, last_updated_ts=1_700_000_000)
    assert sv.feature_id == 2

test("StateValue instantiation", _state_value)

def _match_state_store():
    sv = StateValue(feature_id=2, entity_id=None, value=0.5, last_updated_ts=0)
    store = MatchStateStore(match_id="m-1", match_states=[sv])
    assert store.team_states == []
    assert store.player_states == []
    assert len(store.match_states) == 1

test("MatchStateStore instantiation", _match_state_store)

def _pre_match_info():
    squad = [SquadEntry(jersey_number=9, role=PlayerRole.OUTFIELD, is_starter=True)]
    team = TeamInfo(team_id=1, formation="4-3-3", squad=squad)
    opp  = TeamInfo(team_id=2, formation="4-4-2")
    pmi  = PreMatchInfo(match_id="m-1", team_info=team, opponent_info=opp)
    assert pmi.team_info.squad[0].entity_id is None  # identity not resolved yet
    assert pmi.opponent_info.squad == []

test("PreMatchInfo + TeamInfo + SquadEntry", _pre_match_info)


# ---------------------------------------------------------------------------
# 5. L4 Output models
# ---------------------------------------------------------------------------
print("\n[5] L4 Output models")

from models.l4_output import (
    ShapFeature, Anomaly, Score, CallParameters, StrategyCall, OutputMeta, SequenceModelOutput,
)

def _shap_feature():
    sf = ShapFeature(feature_id=1, shap_value=0.12, feature_value=8.5)
    assert sf.feature_id == 1

test("ShapFeature instantiation", _shap_feature)

def _anomaly():
    sf = ShapFeature(feature_id=1, shap_value=0.8, feature_value=11.0)
    a = Anomaly(
        anomaly_type=AnomalyType.PRESSING_TRIGGER,
        entity_type=EntityType.TEAM,
        entity_id=1,
        confidence=0.91,
        shap_features=[sf],
    )
    assert a.anomaly_type == AnomalyType.PRESSING_TRIGGER
    assert len(a.shap_features) == 1

test("Anomaly instantiation", _anomaly)

def _score():
    s = Score(
        score_type=ScoreType.THREAT_PROBABILITY,
        entity_type=EntityType.PLAYER,
        entity_id=7,
        value=0.77,
        confidence=0.85,
    )
    assert s.shap_features == []

test("Score instantiation", _score)

def _strategy_call():
    sc = StrategyCall(
        call_type=CallType.SUBSTITUTION,
        urgency=Urgency.NEXT_DEAD_BALL,
        entity_type=EntityType.PLAYER,
        entity_id=11,
        confidence=0.72,
        parameters=CallParameters(),
    )
    assert sc.entity_id == 11
    assert sc.shap_features == []

test("StrategyCall instantiation", _strategy_call)

def _strategy_call_team_level():
    sc = StrategyCall(
        call_type=CallType.SHAPE_CHANGE,
        urgency=Urgency.ADVISORY,
        confidence=0.60,
        parameters=CallParameters(),
    )
    assert sc.entity_type is None
    assert sc.entity_id is None

test("StrategyCall team-level (nullable entity)", _strategy_call_team_level)

def _sequence_model_output():
    meta = OutputMeta(window_start_ts=0.0, window_end_ts=5.0, window_size=150, model_version="v1.0")
    out = SequenceModelOutput(
        inference_id="inf-001", match_id="match-1", timestamp=5.0,
        anomalies=[], scores=[], strategy_calls=[], meta=meta,
    )
    assert out.inference_id == "inf-001"
    assert out.meta.model_version == "v1.0"

test("SequenceModelOutput instantiation", _sequence_model_output)


# ---------------------------------------------------------------------------
# 6. Auth models
# ---------------------------------------------------------------------------
print("\n[6] Auth models")

from models.auth import Organization, User, RefreshToken

def _organization():
    org = Organization(
        org_id="org-1", org_name="FC Test",
        license_tier=LicenseTier.PRO,
        license_status=LicenseStatus.ACTIVE,
        license_expiry=datetime(2027, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    assert org.license_tier == LicenseTier.PRO

test("Organization instantiation", _organization)

def _user():
    u = User(
        user_id="u-1", org_id="org-1", username="coach1",
        email="coach@fc.test", password_hash="hashed",
        role=UserRole.HEAD_COACH, is_active=True,
        created_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
    )
    assert u.last_login is None

test("User instantiation + last_login defaults None", _user)

def _refresh_token():
    rt = RefreshToken(
        token_id="tok-1", user_id="u-1", token_hash="abc123",
        issued_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        expires_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        revoked=False,
    )
    assert not rt.revoked

test("RefreshToken instantiation", _refresh_token)


# ---------------------------------------------------------------------------
# 7. Memory store
# ---------------------------------------------------------------------------
print("\n[7] Memory store")

from storage.memory_store import RawFrameBuffer, FrameFeatureBuffer

def _raw_frame_buffer_basic():
    buf = RawFrameBuffer(maxlen=3)
    for i in range(3):
        buf.push(RawFrame(frame_id=i, timestamp=float(i), data=b"x", half=Half.FIRST))
    assert len(buf) == 3
    first = buf.pop()
    assert first.frame_id == 0
    assert len(buf) == 2

test("RawFrameBuffer push/pop/len", _raw_frame_buffer_basic)

def _raw_frame_buffer_overflow():
    buf = RawFrameBuffer(maxlen=2)
    for i in range(4):
        buf.push(RawFrame(frame_id=i, timestamp=float(i), data=b"x", half=Half.FIRST))
    assert len(buf) == 2
    # oldest surviving frame should be frame_id=2
    assert buf.pop().frame_id == 2

test("RawFrameBuffer drop-oldest on overflow", _raw_frame_buffer_overflow)

def _raw_frame_buffer_empty_pop():
    buf = RawFrameBuffer(maxlen=5)
    assert buf.pop() is None

test("RawFrameBuffer pop on empty returns None", _raw_frame_buffer_empty_pop)

def _frame_feature_buffer_basic():
    buf = FrameFeatureBuffer(window_size=3)
    for i in range(3):
        rec = FrameFeatureRecord(frame_id=i, match_id="m-1", timestamp_ms=i*100, half=Half.FIRST)
        buf.push(rec)
    window = buf.get_window("m-1")
    assert len(window) == 3
    assert window[0].frame_id == 0

test("FrameFeatureBuffer push/get_window", _frame_feature_buffer_basic)

def _frame_feature_buffer_isolation():
    buf = FrameFeatureBuffer(window_size=5)
    buf.push(FrameFeatureRecord(frame_id=1, match_id="m-A", timestamp_ms=0, half=Half.FIRST))
    buf.push(FrameFeatureRecord(frame_id=2, match_id="m-B", timestamp_ms=0, half=Half.FIRST))
    assert len(buf.get_window("m-A")) == 1
    assert len(buf.get_window("m-B")) == 1
    assert buf.get_window("m-C") == []

test("FrameFeatureBuffer per-match isolation", _frame_feature_buffer_isolation)

def _frame_feature_buffer_release():
    buf = FrameFeatureBuffer(window_size=5)
    buf.push(FrameFeatureRecord(frame_id=1, match_id="m-1", timestamp_ms=0, half=Half.FIRST))
    buf.release("m-1")
    assert buf.get_window("m-1") == []

test("FrameFeatureBuffer release clears match", _frame_feature_buffer_release)

def _frame_feature_buffer_overflow():
    buf = FrameFeatureBuffer(window_size=2)
    for i in range(4):
        buf.push(FrameFeatureRecord(frame_id=i, match_id="m-1", timestamp_ms=i, half=Half.FIRST))
    window = buf.get_window("m-1")
    assert len(window) == 2
    assert window[0].frame_id == 2  # oldest 2 dropped

test("FrameFeatureBuffer window overflow", _frame_feature_buffer_overflow)


# ---------------------------------------------------------------------------
# 8. Feature registry loader
# ---------------------------------------------------------------------------
print("\n[8] Feature registry loader")

from storage.registry_loader import load_feature_registry

def _registry_load():
    reg = load_feature_registry("config/feature_registry.yaml")
    assert 1 in reg and 2 in reg
    assert reg[1].feature_name == "player_speed"
    assert reg[1].feature_type == FeatureType.FRAME_WISE
    assert reg[1].value_range == (0.0, 12.0)
    assert reg[2].feature_name == "team_possession_pct"
    assert reg[2].update_trigger == UpdateTrigger.CONTINUOUS
    assert reg[2].category == FeatureCategory.TEAM

test("Registry loads and validates YAML", _registry_load)

def _registry_duplicate_detection():
    import tempfile, os
    yaml_content = """
features:
  - feature_id: 1
    feature_name: speed
    feature_description: "Speed"
    feature_type: FRAME_WISE
    category: INDIVIDUAL
  - feature_id: 1
    feature_name: speed_dup
    feature_description: "Duplicate"
    feature_type: FRAME_WISE
    category: INDIVIDUAL
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp = f.name
    try:
        try:
            load_feature_registry(tmp)
            raise AssertionError("Should have raised ValueError for duplicate feature_id")
        except ValueError as e:
            assert "Duplicate feature_id" in str(e)
    finally:
        os.unlink(tmp)

test("Registry rejects duplicate feature_id", _registry_duplicate_detection)


# ---------------------------------------------------------------------------
# 9. Live integration tests (skipped unless INTEGRATION=1)
# ---------------------------------------------------------------------------
# These tests require running Docker services:
#   docker compose up -d
#   python scripts/seed_demo.py   (optional — seed not required for smoke tests)
#
# Enable with:
#   $env:INTEGRATION = "1"; python tests/test_implementation.py   # PowerShell
#   INTEGRATION=1 python tests/test_implementation.py             # bash
# ---------------------------------------------------------------------------

_RUN_INTEGRATION = os.environ.get("INTEGRATION", "").strip() == "1"

if _RUN_INTEGRATION:
    print("\n[9] Live Integration Tests (INTEGRATION=1)")

    import time as _time
    from config.settings import settings
    from storage.redis_store import MatchStateRedisStore, SCOPE_MATCH, SCOPE_TEAM
    from storage.postgres_store import get_session_factory, OrganizationORM
    from models.l3_features import StateValue

    _SMOKE_MATCH_ID = "smoke-test-match-tmp"

    # ---- 9a. Redis connectivity ----
    def _redis_ping():
        store = MatchStateRedisStore(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_auth,
        )
        result = store._r.ping()
        assert result is True, f"Expected PONG (True), got {result!r}"

    test("Redis PING responds", _redis_ping)

    # ---- 9b. Redis StateValue round-trip ----
    def _redis_round_trip():
        store = MatchStateRedisStore(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_auth,
        )
        sv_in = StateValue(
            feature_id=99,
            entity_id=42,
            value=3.14,
            last_updated_ts=int(_time.time()),
        )
        try:
            store.set_state(_SMOKE_MATCH_ID, SCOPE_MATCH, sv_in)
            retrieved = store.get_all(_SMOKE_MATCH_ID, SCOPE_MATCH)
            assert len(retrieved) == 1, f"Expected 1 state value, got {len(retrieved)}"
            sv_out = retrieved[0]
            assert sv_out.feature_id == 99
            assert sv_out.entity_id == 42
            assert abs(sv_out.value - 3.14) < 1e-6, f"Value mismatch: {sv_out.value}"
        finally:
            store.release_match(_SMOKE_MATCH_ID)  # cleanup

    test("Redis StateValue write -> read -> cleanup", _redis_round_trip)

    # ---- 9c. Redis StateSeries append -> get -> cleanup ----
    def _redis_series_round_trip():
        store = MatchStateRedisStore(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_auth,
        )
        try:
            store.append_state_series(_SMOKE_MATCH_ID, SCOPE_TEAM, StateValue(
                feature_id=10, entity_id=1, value=0.1, last_updated_ts=100
            ))
            store.append_state_series(_SMOKE_MATCH_ID, SCOPE_TEAM, StateValue(
                feature_id=10, entity_id=1, value=0.2, last_updated_ts=200
            ))
            
            series = store.get_state_series(_SMOKE_MATCH_ID, SCOPE_TEAM, feature_id=10, entity_id=1)
            assert len(series) == 2, f"Expected 2 values in series, got {len(series)}"
            assert series[0].value == 0.1
            assert series[1].value == 0.2
            assert series[0].last_updated_ts == 100
        finally:
            store.release_match(_SMOKE_MATCH_ID)
            # Verify cleanup
            leftover = store.get_state_series(_SMOKE_MATCH_ID, SCOPE_TEAM, feature_id=10, entity_id=1)
            assert len(leftover) == 0, "Cleanup failed to remove series keys"

    test("Redis StateSeries append -> read -> cleanup", _redis_series_round_trip)

    # ---- 9d. Postgres session factory + table creation ----
    def _postgres_session():
        factory = get_session_factory(settings.postgres_url)
        session = factory()
        try:
            # Simple query — just verify the connection and that tables exist
            count = session.query(OrganizationORM).count()
            assert isinstance(count, int), f"Expected int row count, got {type(count)}"
        finally:
            session.close()

    test("Postgres session factory + table query", _postgres_session)

    # ---- 9d. Postgres ORM insert + query + cleanup ----
    def _postgres_insert_query():
        from datetime import datetime, timezone, timedelta
        from storage.postgres_store import OrganizationORM, UserORM

        factory = get_session_factory(settings.postgres_url)
        session = factory()
        smoke_org_id = "org-smoke-test-tmp"
        try:
            # Insert a smoke-test org (idempotent via merge)
            org = OrganizationORM(
                org_id=smoke_org_id,
                org_name="Smoke Test Org",
                license_tier="BASIC",
                license_status="TRIAL",
                license_expiry=datetime.now(tz=timezone.utc) + timedelta(days=1),
                created_at=datetime.now(tz=timezone.utc),
            )
            session.merge(org)
            session.commit()

            # Query it back
            fetched = session.query(OrganizationORM).filter_by(org_id=smoke_org_id).one()
            assert fetched.org_name == "Smoke Test Org"
            assert fetched.license_tier == "BASIC"
        finally:
            # Cleanup — remove the smoke row so the test is idempotent
            session.query(OrganizationORM).filter_by(org_id=smoke_org_id).delete()
            session.commit()
            session.close()

    test("Postgres ORM insert -> query -> cleanup", _postgres_insert_query)

else:
    print("\n[9] Live Integration Tests — SKIPPED (set INTEGRATION=1 to enable)")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
total  = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed

print("=" * 50)
print(f"Results: {passed}/{total} passed", "" if failed == 0 else f"  ({failed} FAILED)")
print("=" * 50)

if failed:
    print("\nFailed tests:")
    for name, ok, tb in results:
        if not ok:
            print(f"\n  {FAIL} {name}")
            print(tb)
    sys.exit(1)
