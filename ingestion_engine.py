"""
ingestion_engine.py — schema_design/

Integrates the `data_ingestion` StatsBomb source with the `schema_design`
Postgres / Redis / in-memory stores.

Can be used as a class (import & instantiate) or run directly:

    python schema_design/ingestion_engine.py [--match-id 3869685] [--comp-id 43] [--season-id 106]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — must happen before any local imports
# ---------------------------------------------------------------------------
_SCHEMA_ROOT = Path(__file__).resolve().parent        # schema_design/
_REPO_ROOT   = _SCHEMA_ROOT.parent                    # BallKnowledge/
_DI_SRC      = _REPO_ROOT / "data_ingestion" / "src" # data_ingestion/src/

for _p in (_SCHEMA_ROOT, _DI_SRC):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ---------------------------------------------------------------------------
# schema_design imports
# ---------------------------------------------------------------------------
from config.settings import settings                                   # noqa: E402
from storage.postgres_store import get_session_factory, TeamInfoORM, SquadEntryORM  # noqa: E402
from storage.redis_store import MatchStateRedisStore, SCOPE_TEAM       # noqa: E402
from storage.memory_store import FrameFeatureBuffer                    # noqa: E402
from models.l3_features import StateValue, FrameFeatureRecord, FeatureObservation  # noqa: E402
from models.enums import Half                                          # noqa: E402

# ---------------------------------------------------------------------------
# data_ingestion imports
# ---------------------------------------------------------------------------
from data_ingestion.registry import DataSourceRegistry                 # noqa: E402
from data_ingestion.statsbomb_source import StatsBombSource            # noqa: E402
from data_ingestion.custom_types import DataEvent, EventType           # noqa: E402


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class IngestionEngine:
    """
    Orchestrates the full data pipeline for a single match:

        StatsBombSource (data_ingestion)
            └─► handle_event()
                    ├─► FrameFeatureBuffer  (in-memory, rolling window)
                    ├─► Postgres            (team info + squad entries)
                    └─► Redis               (possession state + time-series)

    Usage
    -----
    engine = IngestionEngine(match_id=3869685, competition_id=43, season_id=106)
    engine.run()          # blocks until replay completes
    print(engine.summary())
    """

    def __init__(
        self,
        match_id: int,
        competition_id: int,
        season_id: int,
        *,
        speed_factor: float = 100.0,
        frame_buffer_window: int = 1_000,
        redis_update_every: int = 10,
        show_frames: bool = True,
    ) -> None:
        self.match_id = match_id
        self.competition_id = competition_id
        self.season_id = season_id
        self.speed_factor = speed_factor
        self.frame_buffer_window = frame_buffer_window
        self.redis_update_every = redis_update_every
        self.show_frames = show_frames

        # Internal state trackers
        self._possession_counts: dict[int, int] = {}
        self._frame_count: int = 0

        # Store handles (populated in start())
        self._session_factory = None
        self._redis_store: MatchStateRedisStore | None = None
        self._feature_buf: FrameFeatureBuffer | None = None
        self._registry: DataSourceRegistry | None = None
        self._source: StatsBombSource | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Initialise stores, register source, begin async replay."""
        self._log("=== BallKnowledge Ingestion Engine ===")

        # 1. Stores
        self._log("\n[1/3] Connecting to data stores...")
        self._session_factory = get_session_factory(settings.postgres_url)
        self._redis_store = MatchStateRedisStore(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_auth,
        )
        self._redis_store._r.ping()
        self._feature_buf = FrameFeatureBuffer(window_size=self.frame_buffer_window)
        self._log("      OK.")

        # 2. Registry + Source
        self._log("\n[2/3] Initialising StatsBomb Source...")
        self._registry = DataSourceRegistry()
        self._registry.subscribe_all(event_type=None, handler=self._handle_event)

        self._source = StatsBombSource(
            source_id=f"statsbomb_{self.match_id}",
            competition_id=self.competition_id,
            season_id=self.season_id,
            match_id=self.match_id,
            speed_factor=self.speed_factor,
            carry_tracking_hz=0.0,
        )
        self._registry.register(self._source)

        # 3. Start
        self._log(f"\n[3/3] Starting data stream for Match {self.match_id}...")
        self._registry.connect_all()

    def wait(self) -> None:
        """Block until the replay thread finishes."""
        if self._source is None:
            raise RuntimeError("Engine has not been started. Call start() first.")
        self._source.wait_until_done()

    def run(self) -> None:
        """Convenience: start() then wait()."""
        self.start()
        self.wait()
        self._print_summary()

    def stop(self) -> None:
        """Disconnect all sources cleanly."""
        if self._registry:
            self._registry.disconnect_all()

    def summary(self) -> dict:
        """Return a dict with possession counts and frame buffer stats."""
        total = sum(self._possession_counts.values())
        buf_size = (
            len(self._feature_buf.get_window(str(self.match_id)))
            if self._feature_buf
            else 0
        )
        return {
            "match_id": self.match_id,
            "total_possession_events": total,
            "possession_by_team": {
                tid: {"count": c, "pct": round(c / max(1, total), 4)}
                for tid, c in self._possession_counts.items()
            },
            "frame_buffer_size": buf_size,
            "frames_processed": self._frame_count,
        }

    # ------------------------------------------------------------------
    # Event handler (private)
    # ------------------------------------------------------------------

    def _handle_event(self, event: DataEvent) -> None:
        etype = event.event_type

        # ── 0. Positional → FrameFeatureBuffer ──────────────────────────
        if etype in (EventType.PLAYER_POSITION, EventType.BALL_POSITION):
            self._handle_position(event)

        # ── 1. Match start → Postgres TeamInfo ─────────────────────────
        if etype == EventType.MATCH_START:
            self._handle_match_start(event)

        # ── 1b. Lineup positions → Postgres SquadEntry ─────────────────
        elif (
            etype == EventType.PLAYER_POSITION
            and event.payload.get("source") == "lineup"
        ):
            self._handle_lineup_position(event)

        # ── 2. Possession events → Redis ────────────────────────────────
        if etype in (EventType.PASS, EventType.CARRY, EventType.DRIBBLE):
            self._handle_possession(event)

    # ------------------------------------------------------------------
    # Sub-handlers
    # ------------------------------------------------------------------

    def _handle_position(self, event: DataEvent) -> None:
        x = event.payload.get("x")
        y = event.payload.get("y")
        entity_id = event.payload.get("player_id")  # None for ball

        if x is None or y is None:
            return

        obs_x = FeatureObservation(feature_id=101, entity_id=entity_id, value=x)
        obs_y = FeatureObservation(feature_id=102, entity_id=entity_id, value=y)

        record = FrameFeatureRecord(
            frame_id=event.sequence_number,
            match_id=str(self.match_id),
            timestamp_ms=event.timestamp_ms,
            half=Half.FIRST,  # StatsBomb doesn't guarantee half in every event
            observations=[obs_x, obs_y],
        )
        self._feature_buf.push(record)
        self._frame_count += 1
        if self.show_frames:
            print(f"  [Frame] {record}")

    def _handle_match_start(self, event: DataEvent) -> None:
        team_id = event.payload.get("team_id")
        team_name = event.payload.get("team_name")
        formation = event.metadata.get("formation", "Unknown")

        session = self._session_factory()
        try:
            existing = (
                session.query(TeamInfoORM)
                .filter_by(match_id=str(self.match_id))
                .count()
            )
            side = "self" if existing == 0 else "opponent"

            team_info = (
                session.query(TeamInfoORM)
                .filter_by(match_id=str(self.match_id), team_id=team_id)
                .first()
            )
            if not team_info:
                team_info = TeamInfoORM(
                    match_id=str(self.match_id),
                    side=side,
                    team_id=team_id,
                    formation=formation,
                )
                session.add(team_info)
                session.flush()

            session.commit()
            self._log(
                f"  [Postgres] Team {team_name} (id={team_id}) -> {side}, {formation}"
            )
        except Exception as exc:
            session.rollback()
            self._log(f"  [Postgres ERROR] match_start: {exc}")
        finally:
            session.close()

    def _handle_lineup_position(self, event: DataEvent) -> None:
        team_id = event.payload.get("team_id")
        player_id = event.payload.get("player_id")
        jersey = event.payload.get("jersey_number")
        role_name = event.payload.get("position_name", "OUTFIELD")
        role = "GK" if role_name == "Goalkeeper" else "OUTFIELD"

        session = self._session_factory()
        try:
            team_info = (
                session.query(TeamInfoORM)
                .filter_by(match_id=str(self.match_id), team_id=team_id)
                .first()
            )
            if team_info and jersey is not None:
                exists = (
                    session.query(SquadEntryORM)
                    .filter_by(team_info_id=team_info.id, jersey_number=jersey)
                    .first()
                )
                if not exists:
                    session.add(
                        SquadEntryORM(
                            team_info_id=team_info.id,
                            jersey_number=jersey,
                            entity_id=player_id,
                            role=role,
                            is_starter=True,
                        )
                    )
                    session.commit()
        except Exception as exc:
            session.rollback()
            self._log(f"  [Postgres ERROR] lineup: {exc}")
        finally:
            session.close()

    def _handle_possession(self, event: DataEvent) -> None:
        team_id = event.payload.get("team_id")
        if not team_id:
            return

        self._possession_counts[team_id] = (
            self._possession_counts.get(team_id, 0) + 1
        )
        total = sum(self._possession_counts.values())

        # Flush to Redis every N events
        if total > 0 and total % self.redis_update_every == 0:
            for tid, count in self._possession_counts.items():
                sv = StateValue(
                    feature_id=2,
                    entity_id=tid,
                    value=round(count / total, 4),
                    last_updated_ts=event.timestamp_ms,
                )
                self._redis_store.set_state(str(self.match_id), SCOPE_TEAM, sv)
                self._redis_store.append_state_series(str(self.match_id), SCOPE_TEAM, sv)

        # Progress line every 100 possession events
        if total % 100 == 0:
            buf_size = len(self._feature_buf.get_window(str(self.match_id)))
            self._log(
                f"  [Progress] {event.timestamp_ms}ms | "
                f"Poss Events: {total} | "
                f"Frames: {self._frame_count} | "
                f"FrameBuffer: {buf_size}"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        """Always prints — structural logs are never suppressed."""
        print(msg)

    def _print_summary(self) -> None:
        s = self.summary()
        total = s["total_possession_events"]
        self._log("\n=== Replay Complete ===")
        self._log(f"Frames processed : {s['frames_processed']}")
        self._log(f"FrameBuffer size : {s['frame_buffer_size']}")
        self._log(f"Possession events: {total}")
        for tid, data in s["possession_by_team"].items():
            self._log(f"  Team {tid}: {data['count']} events ({data['pct']:.1%})")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="BallKnowledge Ingestion Engine")
    p.add_argument("--match-id",   type=int, default=3869685, help="StatsBomb match ID")
    p.add_argument("--comp-id",    type=int, default=43,      help="StatsBomb competition ID")
    p.add_argument("--season-id",  type=int, default=106,     help="StatsBomb season ID")
    p.add_argument("--speed",      type=float, default=100.0, help="Replay speed factor")
    p.add_argument("--no-frames",  action="store_true",       help="Suppress per-frame position output (keeps progress + summary)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    engine = IngestionEngine(
        match_id=args.match_id,
        competition_id=args.comp_id,
        season_id=args.season_id,
        speed_factor=args.speed,
        show_frames=not args.no_frames,
    )
    engine.run()
