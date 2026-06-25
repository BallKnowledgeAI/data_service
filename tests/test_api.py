import pytest
from fastapi.testclient import TestClient
import sys
import os

# Ensure the project root is on sys.path so models/ and storage/ are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from main import app
from storage.redis_store import MatchStateRedisStore, SCOPE_MATCH, SCOPE_TEAM, SCOPE_PLAYER
from storage.postgres_store import get_session_factory, Base, TeamInfoORM, SquadEntryORM
from config.settings import settings

client = TestClient(app)

# Test data
MATCH_ID = "test_match_001"
TEAM_ID_1 = 101
TEAM_ID_2 = 102

@pytest.fixture(scope="function", autouse=True)
def setup_database():
    # Setup Postgres - Drop all and recreate to ensure clean schema
    session_factory = get_session_factory(settings.postgres_url)
    db = session_factory()
    
    # We can access the engine from the session factory's bind
    engine = db.get_bind()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    
    # Setup Redis
    redis_store = MatchStateRedisStore(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_auth,
    )
    redis_store.release_match(MATCH_ID)
    
    yield
    
    # Cleanup after tests
    Base.metadata.drop_all(engine)
    db.close()
    redis_store.release_match(MATCH_ID)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Redis Tests
def test_set_and_get_match_state():
    # Set state
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/state/{SCOPE_MATCH}",
        json={
            "feature_id": 1,
            "entity_id": 0,
            "value": 0.75,
            "last_updated_ts": 1000
        }
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success"}

    # Get state
    response = client.get(f"/api/v1/matches/{MATCH_ID}/state/{SCOPE_MATCH}")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["feature_id"] == 1
    assert data[0]["value"] == 0.75


def test_append_and_get_state_series():
    # Append first value in minute 0
    client.post(
        f"/api/v1/matches/{MATCH_ID}/series/{SCOPE_PLAYER}",
        json={
            "feature_id": 10,
            "entity_id": 99,
            "value": 30.0,
            "last_updated_ts": 1000  # < 60000
        }
    )
    
    # Append second value in minute 0 (should average to 35.0)
    client.post(
        f"/api/v1/matches/{MATCH_ID}/series/{SCOPE_PLAYER}",
        json={
            "feature_id": 10,
            "entity_id": 99,
            "value": 40.0,
            "last_updated_ts": 2000  # < 60000
        }
    )
    
    # Append third value in minute 1 (this forces flush of minute 0 bucket)
    client.post(
        f"/api/v1/matches/{MATCH_ID}/series/{SCOPE_PLAYER}",
        json={
            "feature_id": 10,
            "entity_id": 99,
            "value": 50.0,
            "last_updated_ts": 61000  # > 60000 (minute 1)
        }
    )

    # Get series (should return the flushed average for minute 0)
    response = client.get(
        f"/api/v1/matches/{MATCH_ID}/series/{SCOPE_PLAYER}",
        params={"feature_id": 10, "entity_id": 99}
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["value"] == 35.0


def test_release_match_redis():
    client.post(
        f"/api/v1/matches/{MATCH_ID}/state/{SCOPE_MATCH}",
        json={
            "feature_id": 1,
            "entity_id": 0,
            "value": 0.75,
            "last_updated_ts": 1000
        }
    )
    
    response = client.delete(f"/api/v1/matches/{MATCH_ID}")
    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    
    # Verify it's deleted
    response = client.get(f"/api/v1/matches/{MATCH_ID}/state/{SCOPE_MATCH}")
    assert response.status_code == 200
    assert response.json() == []


# Postgres Tests
def test_register_team_and_duplicate():
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/teams",
        json={"team_id": TEAM_ID_1, "formation": "4-3-3"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "created"
    assert "id" in data

    # Test duplicate registration
    response2 = client.post(
        f"/api/v1/matches/{MATCH_ID}/teams",
        json={"team_id": TEAM_ID_1, "formation": "4-3-3"}
    )
    assert response2.status_code == 200
    assert response2.json()["status"] == "already_exists"


def test_register_squad_entry():
    # First register the team
    client.post(
        f"/api/v1/matches/{MATCH_ID}/teams",
        json={"team_id": TEAM_ID_1, "formation": "4-3-3"}
    )

    # Then register to the team
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/teams/{TEAM_ID_1}/squad",
        json={
            "jersey_number": 10,
            "entity_id": 1001,
            "role": "ATTACKER",
            "is_starter": True
        }
    )
    assert response.status_code == 200
    assert response.json()["status"] == "created"

    # Test duplicate
    response2 = client.post(
        f"/api/v1/matches/{MATCH_ID}/teams/{TEAM_ID_1}/squad",
        json={
            "jersey_number": 10,
            "entity_id": 1001,
            "role": "ATTACKER",
            "is_starter": True
        }
    )
    assert response2.status_code == 200
    assert response2.json()["status"] == "already_exists"


def test_register_squad_entry_missing_team():
    # Don't register a team, try to add a squad entry directly
    response = client.post(
        f"/api/v1/matches/{MATCH_ID}/teams/9999/squad",
        json={
            "jersey_number": 7,
            "entity_id": 1007,
            "role": "MIDFIELDER",
            "is_starter": True
        }
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Team not found for this match"


def test_update_identity():
    # Setup team and squad entry
    client.post(
        f"/api/v1/matches/{MATCH_ID}/teams",
        json={"team_id": TEAM_ID_1, "formation": "4-3-3"}
    )
    client.post(
        f"/api/v1/matches/{MATCH_ID}/teams/{TEAM_ID_1}/squad",
        json={
            "jersey_number": 10,
            "entity_id": 1001,
            "role": "ATTACKER",
            "is_starter": True
        }
    )

    # Upsert identity resolution on an existing jersey
    response = client.patch(
        f"/api/v1/matches/{MATCH_ID}/teams/{TEAM_ID_1}/squad/10/identity",
        json={"entity_id": 9999}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_update_identity_missing_jersey():
    # Setup team but do NOT register jersey #99
    client.post(
        f"/api/v1/matches/{MATCH_ID}/teams",
        json={"team_id": TEAM_ID_1, "formation": "4-3-3"}
    )

    # Attempt to resolve identity for a jersey that was never registered
    response = client.patch(
        f"/api/v1/matches/{MATCH_ID}/teams/{TEAM_ID_1}/squad/99/identity",
        json={"entity_id": 9999}
    )
    assert response.status_code == 404
    assert "Jersey #99" in response.json()["detail"]
