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
    team_id = Column(Integer, nullable=False)
    formation = Column(String, nullable=False)
    squad = relationship("SquadEntryORM", back_populates="team", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("match_id", "team_id", name="uq_match_team"),)


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

"""
Caveat: this only creates tables, it never alters existing ones. If you later
add a column to UserORM, this line won't add that column to an already-existing
users table — you'd need a real migration tool (Alembic) for schema changes after
the first run. Fine for initial development, not sufficient for production
schema evolution.
"""

# Use PgBouncer url to pool connections efficiently.
def get_session_factory(db_url: str):
    engine = create_engine(db_url, pool_size=10, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def upsert_identity_resolution(session_factory, match_id: str, team_id: int, jersey_number: int, entity_id: int) -> None:
    """Fire-and-forget, async-callable. Idempotent UPSERT keyed on (team_info_id, jersey_number).
    Safe to call concurrently — on conflict, overwrites entity_id in place.
    Call this off the hot path (e.g. via a background task queue) — does not block pipeline progress."""
    session = session_factory()
    try:
        team = session.query(TeamInfoORM).filter_by(match_id=match_id, team_id=team_id).one()
        stmt = (
            pg_insert(SquadEntryORM)
            .values(
                team_info_id=team.id,
                jersey_number=jersey_number,
                entity_id=entity_id,
                role="UNKNOWN",       # required by NOT NULL constraint for the insert part
                is_starter=False      # required by NOT NULL constraint for the insert part
            )
            .on_conflict_do_update(
                constraint="uq_team_jersey",
                set_={"entity_id": entity_id},
            )
        )
        session.execute(stmt)
        session.commit()
    finally:
        session.close()
