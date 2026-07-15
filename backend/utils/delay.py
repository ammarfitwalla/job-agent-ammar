import time
import random


def delay(min_secs: float, max_secs: float):
    """Random sleep between min_secs and max_secs."""
    time.sleep(random.uniform(min_secs, max_secs))
