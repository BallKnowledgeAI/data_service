"""
scripts/seed_demo.py — Populate Redis and Postgres with demo data.

Run this AFTER `docker compose up -d` (once both services are healthy).

    python scripts/seed_demo.py

The script is fully idempotent — safe to run multiple times.
- Postgres rows use INSERT ... ON CONFLICT DO NOTHING / DO UPDATE.
- Redis writes are plain HSET (overwrite is fine for demo state).

Exit codes:
  0 — success
  1 — connection / seed failure (details printed to stderr)
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Make the project root importable regardless of where the script is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)  # so relative YAML paths work

from config.settings import settings  # noqa: E402  (after sys.path tweak)
from storage.postgres_store import (  # noqa: E402
    Base,
    OrganizationORM,
    UserORM,
    RefreshTokenORM,
    TeamInfoORM,
    SquadEntryORM,
    get_session_factory,
)
from storage.redis_store import MatchStateRedisStore, SCOPE_MATCH, SCOPE_TEAM, SCOPE_PLAYER  # noqa: E402
from models.l3_features import StateValue  # noqa: E402


# ---------------------------------------------------------------------------
# Demo constants
# ---------------------------------------------------------------------------
DEMO_ORG_ID   = "org-demo"
DEMO_USER_ID  = "user-demo-coach"
DEMO_TOKEN_ID = "tok-demo-001"
DEMO_MATCH_ID = "match-demo-2026"

NOW = datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Postgres seed
# ---------------------------------------------------------------------------

def seed_postgres(session_factory) -> None:
    print("  [Postgres] Seeding tables ...")
    session = session_factory()
    try:
        # ---- Organisation ----
        org = OrganizationORM(
            org_id=DEMO_ORG_ID,
            org_name="FC Demo Club",
            license_tier="PRO",
            license_status="ACTIVE",
            license_expiry=NOW + timedelta(days=365),
            created_at=NOW,
        )
        session.merge(org)  # INSERT or UPDATE by PK — idempotent

        # ---- User (head coach) ----
        user = UserORM(
            user_id=DEMO_USER_ID,
            org_id=DEMO_ORG_ID,
            username="demo_coach",
            email="coach@fc-demo.test",
            password_hash="$2b$12$DEMO_HASH_NOT_FOR_PRODUCTION",
            role="HEAD_COACH",
            is_active=True,
            created_at=NOW,
            last_login=NOW,
        )
        session.merge(user)

        # ---- Refresh token ----
        token = RefreshTokenORM(
            token_id=DEMO_TOKEN_ID,
            user_id=DEMO_USER_ID,
            token_hash="demo_token_hash_abc123",
            issued_at=NOW,
            expires_at=NOW + timedelta(days=7),
            revoked=False,
        )
        session.merge(token)

        # ---- Team info (self side) ----
        # Use merge on the unique constraint match_id+side by querying first.
        self_team = (
            session.query(TeamInfoORM)
            .filter_by(match_id=DEMO_MATCH_ID, side="self")
            .first()
        )
        if self_team is None:
            self_team = TeamInfoORM(
                match_id=DEMO_MATCH_ID,
                side="self",
                team_id=101,
                formation="4-3-3",
            )
            session.add(self_team)
            session.flush()  # get auto-assigned id

        # ---- Squad entries ----
        _upsert_squad(session, self_team, [
            dict(jersey_number=1,  role="GK",      is_starter=True,  entity_id=1001),
            dict(jersey_number=9,  role="OUTFIELD", is_starter=True,  entity_id=1009),
            dict(jersey_number=10, role="OUTFIELD", is_starter=True,  entity_id=1010),
            dict(jersey_number=11, role="OUTFIELD", is_starter=True,  entity_id=1011),
        ])

        # ---- Team info (opponent side) ----
        opp_team = (
            session.query(TeamInfoORM)
            .filter_by(match_id=DEMO_MATCH_ID, side="opponent")
            .first()
        )
        if opp_team is None:
            opp_team = TeamInfoORM(
                match_id=DEMO_MATCH_ID,
                side="opponent",
                team_id=202,
                formation="4-4-2",
            )
            session.add(opp_team)
            session.flush()

        _upsert_squad(session, opp_team, [
            dict(jersey_number=1,  role="GK",      is_starter=True,  entity_id=2001),
            dict(jersey_number=7,  role="OUTFIELD", is_starter=True,  entity_id=2007),
            dict(jersey_number=8,  role="OUTFIELD", is_starter=True,  entity_id=2008),
        ])

        session.commit()
        print("  [Postgres] OK: Demo rows committed.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _upsert_squad(session, team: TeamInfoORM, entries: list[dict]) -> None:
    """Merge squad entries by (team_info_id, jersey_number)."""
    existing = {e.jersey_number: e for e in session.query(SquadEntryORM).filter_by(team_info_id=team.id).all()}
    for e in entries:
        if e["jersey_number"] in existing:
            row = existing[e["jersey_number"]]
            row.entity_id   = e.get("entity_id")
            row.role        = e["role"]
            row.is_starter  = e["is_starter"]
        else:
            session.add(SquadEntryORM(
                team_info_id=team.id,
                jersey_number=e["jersey_number"],
                entity_id=e.get("entity_id"),
                role=e["role"],
                is_starter=e["is_starter"],
            ))


# ---------------------------------------------------------------------------
# Redis seed
# ---------------------------------------------------------------------------

def seed_redis(store: MatchStateRedisStore) -> None:
    print("  [Redis] Seeding match state ...")
    ts = int(time.time())

    # Match-scope: threat probability for the whole match
    store.set_state(DEMO_MATCH_ID, SCOPE_MATCH, StateValue(
        feature_id=3,
        entity_id=None,
        value=0.42,
        last_updated_ts=ts,
    ))

    # Team-scope: possession percentage for self team (team_id=101)
    store.set_state(DEMO_MATCH_ID, SCOPE_TEAM, StateValue(
        feature_id=2,
        entity_id=101,
        value=0.58,
        last_updated_ts=ts,
    ))

    # Player-scope: speed for player entity_id=1009
    store.set_state(DEMO_MATCH_ID, SCOPE_PLAYER, StateValue(
        feature_id=1,
        entity_id=1009,
        value=7.3,
        last_updated_ts=ts,
    ))

    print("  [Redis] OK: Demo state written.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print("\n=== Tactical Analysis Pipeline - Demo Seed ===\n")

    # ---- Postgres ----
    print("[1/2] Connecting to Postgres ...")
    try:
        session_factory = get_session_factory(settings.postgres_url)
        seed_postgres(session_factory)
    except Exception as exc:
        print(f"\n[ERROR] Postgres seed failed: {exc}", file=sys.stderr)
        print("  -> Is `docker compose up -d` running and healthy?", file=sys.stderr)
        return 1

    # ---- Redis ----
    print("\n[2/2] Connecting to Redis ...")
    try:
        store = MatchStateRedisStore(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_auth,
        )
        # Quick connectivity check before writing
        store._r.ping()
        seed_redis(store)
    except Exception as exc:
        print(f"\n[ERROR] Redis seed failed: {exc}", file=sys.stderr)
        print("  -> Is `docker compose up -d` running and healthy?", file=sys.stderr)
        return 1

    print("\n=== Seed complete ===")
    print(f"\n  Match ID : {DEMO_MATCH_ID}")
    print(f"  Org ID   : {DEMO_ORG_ID}")
    print(f"  User ID  : {DEMO_USER_ID}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
