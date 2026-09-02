import os
import sys
import time
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import api.routes.scrape as scrape_mod  # noqa: E402
import db  # noqa: E402
import match_engine.relevance_engine  # noqa: E402
import utils.delay  # noqa: E402
import utils.experience_level  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------

def _job(n):
    return {
        "url": f"https://example.com/job-{n}",
        "title": f"Software Engineer {n}",
        "company": "Acme",
        "location": "New York, NY",
        "description": "Build things with care.",
        "tags": [],
    }


_FAKE_MOD = types.ModuleType("scrapers.fake_mod")
_FAKE_CALLS = {"n": 0}
_PLANS = {}
_LOGS = []


def _fake_scrape(**kwargs):
    _FAKE_CALLS["n"] += 1
    role = kwargs.get("roles", ["role"])[0]
    plan = _PLANS.get(role, [])

    def gen():
        for pause, batch in plan:
            if pause:
                time.sleep(pause)
            yield batch

    return gen()


_FAKE_MOD.scrape_fake = _fake_scrape


@pytest.fixture(autouse=True)
def _scrape_env(monkeypatch):
    monkeypatch.setattr(sys, "modules", {**sys.modules, "scrapers.fake_mod": _FAKE_MOD})
    monkeypatch.setattr(scrape_mod, "SITE_MAP", {"fake": ("fake_mod", "scrape_fake")})
    monkeypatch.setattr(scrape_mod, "SCRAPE_COMBO_STALL_SECONDS", 60)
    monkeypatch.setattr(scrape_mod, "SCRAPE_GOOD_TARGET_PER_COMBO", 50)

    monkeypatch.setattr(utils.delay, "delay", lambda a, b=None: None)
    monkeypatch.setattr(match_engine.relevance_engine, "role_match_count", lambda title, roles: 5)
    monkeypatch.setattr(utils.experience_level, "detect_experience_level", lambda title, desc: "mid")
    monkeypatch.setattr(utils.experience_level, "level_from_job_level", lambda job_level: None)
    monkeypatch.setattr(utils.experience_level, "yoe_bucket_from_job", lambda title, desc, job_level: "3-5")

    monkeypatch.setattr(db, "save_cache_entry", lambda *a, **k: None)
    monkeypatch.setattr(db, "touch_prewarm_combo", lambda *a, **k: None)

    _LOGS.clear()
    monkeypatch.setattr(scrape_mod, "log", lambda msg, sid=None: _LOGS.append((sid, msg)))

    _FAKE_CALLS["n"] = 0
    _PLANS.clear()
    yield


def _combo(role, site="fake"):
    return {"role": role, "site": site, "location": "", "indeed_country": "",
            "city": "", "state": "", "country": ""}


# ---------------------------------------------------------------------------
# 1) Stall watchdog: a combo with no job growth past the window is skipped
# ---------------------------------------------------------------------------

def test_stalled_combo_is_skipped_but_next_still_runs(monkeypatch):
    monkeypatch.setattr(scrape_mod, "SCRAPE_COMBO_STALL_SECONDS", 0.1)
    _PLANS["staller"] = [(0.07, []), (0.07, []), (0.07, [])]
    _PLANS["yielder"] = [(0, [_job("a"), _job("b")])]

    combos = [_combo("staller"), _combo("yielder")]
    jobs, seen = scrape_mod._scrape_combos(None, combos, keywords=[])

    assert any("Stalled" in msg for _, msg in _LOGS)
    assert any("staller" in msg for _, msg in _LOGS)
    assert len(jobs) == 2
    assert _FAKE_CALLS["n"] == 2


# ---------------------------------------------------------------------------
# 1b) A slow-but-productive batch (arrives past the window but with jobs) must
#     never be stalled — only empty feedback counts as a stall
# ---------------------------------------------------------------------------

def test_slow_nonempty_batch_is_not_stalled(monkeypatch):
    monkeypatch.setattr(scrape_mod, "SCRAPE_COMBO_STALL_SECONDS", 0.1)
    _PLANS["slow"] = [(0.07, []), (0.07, [_job("1"), _job("2")])]

    jobs, seen = scrape_mod._scrape_combos(None, [_combo("slow")], keywords=[])

    assert len(jobs) == 2
    assert not any("Stalled" in msg for _, msg in _LOGS)


# ---------------------------------------------------------------------------
# 2) Per-combo target: combo stops once its new-job count reaches the target;
#    remaining batches of the same combo are not consumed
# ---------------------------------------------------------------------------

def test_combo_stops_at_target_and_continues_next(monkeypatch):
    monkeypatch.setattr(scrape_mod, "SCRAPE_GOOD_TARGET_PER_COMBO", 10)
    # 3 batches available; combo should stop after the 2nd reaches 10
    _PLANS["yielder"] = [
        (0, [_job("1"), _job("2"), _job("3"), _job("4"), _job("5")]),
        (0, [_job("6"), _job("7"), _job("8"), _job("9"), _job("10")]),
        (0, [_job("11"), _job("12"), _job("13"), _job("14"), _job("15")]),
    ]
    _PLANS["second"] = [(0, [_job("a"), _job("b"), _job("c")])]

    combos = [_combo("yielder"), _combo("second")]
    jobs, seen = scrape_mod._scrape_combos(None, combos, keywords=[])

    assert any("Enough relevant (10)" in msg for _, msg in _LOGS)
    assert any("yielder" in msg for _, msg in _LOGS)
    # 10 from combo 1 (3rd batch dropped) + 3 from combo 2
    assert len(jobs) == 13
    assert _FAKE_CALLS["n"] == 2


# ---------------------------------------------------------------------------
# 3) Cancel: jobs collected so far are preserved and session ends done
# ---------------------------------------------------------------------------

def test_cancel_preserves_jobs(monkeypatch):
    stored_raw = []
    session_updates = []
    monkeypatch.setattr(scrape_mod, "_is_cancelled", lambda sid: True)
    monkeypatch.setattr(scrape_mod, "set_raw_jobs", lambda sid, jobs: stored_raw.append(list(jobs)))
    monkeypatch.setattr(scrape_mod, "update_session", lambda sid, **kw: session_updates.append((sid, kw)))
    monkeypatch.setattr(scrape_mod, "get_session", lambda sid: {})

    initial = [_job("cached-1"), _job("cached-2")]
    jobs, seen = scrape_mod._scrape_combos(
        "test-cancel", [_combo("yielder")], keywords=[], initial_jobs=initial)

    assert {j["url"] for j in jobs} == {j["url"] for j in initial}
    assert stored_raw and {j["url"] for j in stored_raw[0]} == {j["url"] for j in initial}
    assert any(sid == "test-cancel" and kw.get("status") == "done" for sid, kw in session_updates)