from collections import deque
from threading import Lock
from models.l1_ingestion import RawFrame
from models.l3_features import FrameFeatureRecord


class RawFrameBuffer:
    """Bounded queue, drop-oldest policy.

    NOTE: drop-oldest is a tentative choice addressing the CV-layer throughput
    bottleneck — not finalized. Alternatives under consideration: drop-newest,
    fixed-interval downsampling, disk-backed overflow, adaptive backpressure,
    dynamic resolution reduction. Revisit once CV throughput is benchmarked.
    """


    def __init__(self, maxlen: int):
        self._buf: deque[RawFrame] = deque(maxlen=maxlen)
        self._lock = Lock()

    def push(self, frame: RawFrame) -> None:
        with self._lock:
            self._buf.append(frame)  # deque(maxlen=N) auto-drops oldest on overflow

    def pop(self) -> RawFrame | None:
        with self._lock:
            return self._buf.popleft() if self._buf else None

    def __len__(self) -> int:
        return len(self._buf)


class FrameFeatureBuffer:
    """Per-match_id deque of FrameFeatureRecord, window size W."""

    def __init__(self, window_size: int):
        self._window_size = window_size
        self._buffers: dict[str, deque[FrameFeatureRecord]] = {}
        self._lock = Lock()

    def _get_or_create(self, match_id: str) -> deque[FrameFeatureRecord]:
        if match_id not in self._buffers:
            self._buffers[match_id] = deque(maxlen=self._window_size)
        return self._buffers[match_id]

    def push(self, record: FrameFeatureRecord) -> None:
        with self._lock:
            self._get_or_create(record.match_id).append(record)

    def get_window(self, match_id: str) -> list[FrameFeatureRecord]:
        with self._lock:
            return list(self._buffers.get(match_id, []))

    def release(self, match_id: str) -> None:
        """Call on match end to free memory — see cleanup note in storage guide."""
        with self._lock:
            self._buffers.pop(match_id, None)
