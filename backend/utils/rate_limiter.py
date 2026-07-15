import time
from collections import defaultdict

_limits: dict[str, list] = defaultdict(list)


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    now = time.time()
    timestamps = _limits[key]
    _limits[key] = [t for t in timestamps if now - t < window_seconds]
    if len(_limits[key]) >= max_requests:
        return False
    _limits[key].append(now)
    return True
