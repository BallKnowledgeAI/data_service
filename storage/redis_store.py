import json
import time
import redis
from models.l3_features import StateValue, ScalarValue

SCOPE_MATCH = "match"
SCOPE_TEAM = "team"
SCOPE_PLAYER = "player"


class MatchStateRedisStore:
    def __init__(self, host: str, port: int = 6379, password: str | None = None, ttl_seconds: int = 4 * 3600):
        self._r = redis.Redis(host=host, port=port, password=password, decode_responses=True)
        self._ttl = ttl_seconds  # backstop cleanup in case explicit DEL on match-end is missed

    @staticmethod
    def _key(match_id: str, scope: str) -> str:
        return f"matchstate:{match_id}:{scope}"

    @staticmethod
    def _field(feature_id: int, entity_id: int | None) -> str:
        return f"{feature_id}:{entity_id if entity_id is not None else ''}"

    def set_state(self, match_id: str, scope: str, sv: StateValue) -> None:
        key = self._key(match_id, scope)
        field = self._field(sv.feature_id, sv.entity_id)
        # sv.value is now a StateValueData concrete type — call serialize() for JSON
        value = json.dumps({"value": sv.value.serialize(), "last_updated_ts": sv.last_updated_ts})
        pipe = self._r.pipeline()
        pipe.hset(key, field, value)
        pipe.expire(key, self._ttl)
        pipe.execute()

    def get_all(self, match_id: str, scope: str) -> list[StateValue]:
        key = self._key(match_id, scope)
        raw = self._r.hgetall(key)
        result = []
        for field, value in raw.items():
            feature_id_str, entity_id_str = field.split(":")
            parsed = json.loads(value)
            # NOTE: get_all returns ScalarValue wrappers for now.
            # Full polymorphic deserialisation (using a type discriminator) is deferred
            # to the Redis persistence task (see implementation plan §redis_store future work).
            result.append(StateValue(
                feature_id=int(feature_id_str),
                entity_id=int(entity_id_str) if entity_id_str else None,
                value=ScalarValue.deserialize(parsed["value"]),
                last_updated_ts=parsed["last_updated_ts"],
            ))
        return result

    @staticmethod
    def _series_key(match_id: str, scope: str, feature_id: int, entity_id: int | None) -> str:
        return f"matchstate_series:{match_id}:{scope}:{feature_id}:{entity_id if entity_id is not None else ''}"

    def append_state_series(self, match_id: str, scope: str, sv: StateValue) -> None:
        """Appends a state value to a time-series list for post-match trend analysis.
        
        ScalarValue features use a 1-minute averaging bucket to prevent noise.
        Non-scalar values are appended directly.
        """
        key = self._series_key(match_id, scope, sv.feature_id, sv.entity_id)
        idx_key = f"matchstate_series_idx:{match_id}"
        
        # Non-scalars bypass the averaging bucket and go straight to the list
        if not isinstance(sv.value, ScalarValue):
            value_to_append = json.dumps({"value": sv.value.serialize(), "last_updated_ts": sv.last_updated_ts})
            pipe = self._r.pipeline()
            pipe.rpush(key, value_to_append)
            pipe.expire(key, self._ttl)
            pipe.sadd(idx_key, key)
            pipe.expire(idx_key, self._ttl)
            pipe.execute()
            return

        # Scalar logic (averaging)
        raw_scalar: float = sv.value.serialize()

        temp_key = f"{key}:temp"
        current_minute = sv.last_updated_ts // 60000
        raw_temp = self._r.hgetall(temp_key)

        if not raw_temp:
            # First value, initialize the bucket
            pipe = self._r.pipeline()
            pipe.hset(temp_key, mapping={"minute": current_minute, "sum": raw_scalar, "count": 1, "last_ts": sv.last_updated_ts})
            pipe.expire(temp_key, self._ttl)
            pipe.sadd(idx_key, temp_key)  # Track temp key for cleanup
            pipe.execute()
            return
            
        stored_minute = int(raw_temp.get("minute", 0))
        
        if current_minute == stored_minute:
            # We are in the same minute: Accumulate to calculate the average
            pipe = self._r.pipeline()
            pipe.hincrbyfloat(temp_key, "sum", raw_scalar)
            pipe.hincrby(temp_key, "count", 1)
            pipe.hset(temp_key, "last_ts", sv.last_updated_ts)
            pipe.execute()

        elif current_minute > stored_minute:
            # Minute has rolled over: Flush the average of the old bucket to the time series
            old_sum = float(raw_temp.get("sum", 0))
            old_count = int(raw_temp.get("count", 1))
            old_last_ts = int(raw_temp.get("last_ts", sv.last_updated_ts))
            
            avg_value = old_sum / old_count
            value_to_append = json.dumps({"value": round(avg_value, 4), "last_updated_ts": old_last_ts})
            
            pipe = self._r.pipeline()
            # Push the averaged value
            pipe.rpush(key, value_to_append)
            pipe.expire(key, self._ttl)
            
            # Reset bucket for the new minute
            pipe.hset(temp_key, mapping={"minute": current_minute, "sum": raw_scalar, "count": 1, "last_ts": sv.last_updated_ts})
            pipe.expire(temp_key, self._ttl)
            
            # Track keys for cleanup
            pipe.sadd(idx_key, key)
            pipe.expire(idx_key, self._ttl)
            pipe.execute()

    def get_state_series(self, match_id: str, scope: str, feature_id: int, entity_id: int | None) -> list[StateValue]:
        """Retrieves the full time-series of state values for a specific feature/entity.

        Series entries are always scalar averages, so deserialized as ScalarValue.
        """
        key = self._series_key(match_id, scope, feature_id, entity_id)
        raw_list = self._r.lrange(key, 0, -1)
        result = []
        for raw in raw_list:
            parsed = json.loads(raw)
            result.append(StateValue(
                feature_id=feature_id,
                entity_id=entity_id,
                value=ScalarValue.deserialize(parsed["value"]),
                last_updated_ts=parsed["last_updated_ts"],
            ))
        return result

    def release_match(self, match_id: str) -> None:
        """Call on match end — explicit cleanup; TTL is the backstop."""
        pipe = self._r.pipeline()
        for scope in (SCOPE_MATCH, SCOPE_TEAM, SCOPE_PLAYER):
            pipe.delete(self._key(match_id, scope))
            
        # Clean up series keys
        idx_key = f"matchstate_series_idx:{match_id}"
        series_keys = self._r.smembers(idx_key)
        for k in series_keys:
            pipe.delete(k)
        pipe.delete(idx_key)
        pipe.execute()


# Usage:
# store = MatchStateRedisStore(host="10.0.0.5")
# store.set_state(match_id, SCOPE_TEAM, StateValue(feature_id=12, entity_id=1, value=0.63, last_updated_ts=int(time.time())))
# team_states = store.get_all(match_id, SCOPE_TEAM)
