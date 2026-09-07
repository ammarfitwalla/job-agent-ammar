import threading
import time
from collections import defaultdict

_limits: dict[str, list] = defaultdict(list)
_sweep_at = 0.0
_lock = threading.Lock()

# Idle keys are evicted on a periodic sweep so the map stays bounded.
# Callers must use window_seconds smaller than this threshold.
_SWEEP_SECONDS = 600.0


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    global _sweep_at
    now = time.time()
    with _lock:
        if now >= _sweep_at:
            _sweep_at = now + _SWEEP_SECONDS
            cutoff = now - _SWEEP_SECONDS
            for k in [k for k, v in _limits.items() if not v or v[-1] < cutoff]:
                _limits.pop(k, None)
        timestamps = _limits[key]
        _limits[key] = [t for t in timestamps if now - t < window_seconds]
        if len(_limits[key]) >= max_requests:
            return False
        _limits[key].append(now)
        return True