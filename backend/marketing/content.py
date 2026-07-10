from config import X_TEMPLATES, X_SCHEDULE
from datetime import datetime
import random


def resolve_template(template_key: str) -> str | None:
    return X_TEMPLATES.get(template_key)


def schedule_for_today() -> list[dict]:
    today = datetime.now().strftime("%a").lower()[:3]
    return [e for e in X_SCHEDULE if e.get("day", "").lower()[:3] == today]


def pick_time(window: str) -> tuple[int, int]:
    try:
        start, end = window.split("-")
        sh, sm = start.strip().split(":")
        eh, em = end.strip().split(":")
        start_min = int(sh) * 60 + int(sm)
        end_min = int(eh) * 60 + int(em)
        pick = random.randint(start_min, end_min)
        return divmod(pick, 60)
    except:
        return 9, 0
