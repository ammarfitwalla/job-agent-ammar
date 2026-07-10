from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from utils.logger import log
from config import X_ENABLED
from marketing.content import schedule_for_today, resolve_template, pick_time


def _post_tweet(template_key: str):
    text = resolve_template(template_key)
    if not text:
        log(f"[X] Unknown template: {template_key}")
        return
    from marketing.twitter import TwitterClient
    client = TwitterClient()
    log(f"[X] Posting tweet from template '{template_key}'")
    ok, err = client.post_tweet(text)
    if not ok:
        log(f"[X] Tweet failed: {err}")


def _schedule_today(scheduler):
    entries = schedule_for_today()
    if not entries:
        log(f"[X] No tweets scheduled for today ({datetime.now().strftime('%A')})")
        return

    for entry in entries:
        h, m = pick_time(entry.get("window", "09:00-12:00"))
        tpl = entry.get("template", "")
        trigger = CronTrigger(hour=h, minute=m, day_of_week=datetime.now().strftime("%a").lower()[:3])
        scheduler.add_job(_post_tweet, trigger, args=[tpl], id=f"x_tweet_{tpl}")
        log(f"[X] Scheduled '{tpl}' at {h:02d}:{m:02d}")


def _reschedule_daily(scheduler):
    scheduler.remove_all_jobs()
    _schedule_today(scheduler)


def start_scheduler():
    if not X_ENABLED:
        log("[X] Twitter marketing disabled (X_ENABLED=False)")
        return

    scheduler = BackgroundScheduler(daemon=True)
    _schedule_today(scheduler)
    scheduler.add_job(lambda: _reschedule_daily(scheduler), CronTrigger(hour=0, minute=1), id="x_reschedule")
    scheduler.start()
    log("[X] Twitter scheduler started")
