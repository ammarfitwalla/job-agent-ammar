import random
import time

def delay(min_sec=2.0, max_sec=5.0):
    time.sleep(random.uniform(min_sec, max_sec))
