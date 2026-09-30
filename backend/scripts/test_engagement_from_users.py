"""Data-driven engagement scenarios.

Every case is a row in `users`, run through the real producer
(scheduler.enqueue_engagement_emails) and asserted on the email it produced.
Roles, cities, states, markets and the postings themselves are discovered from
the live job_cache, so no case depends on a hardcoded role/location/job. The only
hand-built values are the deliberately invalid ones: blank fields, flags, dates
and mangled role strings.

The live database is never modified. It is copied to a temp file first, and the
copy's existing user/visit/queue rows are dropped so only the test subject is
eligible while the real job cache stays intact.

    python scripts/test_engagement_from_users.py
    python scripts/test_engagement_from_users.py --send
"""
import argparse
import datetime as dt
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_ALLOW_DEV_SECRET", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config  # noqa: E402
import db  # noqa: E402
import scheduler  # noqa: E402
from emails.unsubscribe import build_unsubscribe_url, validate_unsubscribe  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DB = os.path.join(BACKEND, "job_agent.db")
RECIPIENT = os.environ.get("ENGAGEMENT_TEST_EMAIL") or getattr(config, "ADMIN_EMAIL", "")
HOURS = int(getattr(config, "ENGAGEMENT_CACHE_HOURS_OLD", 168))
BASE = (f"internship_mode=0 AND hours_old={HOURS} AND is_remote=0 "
        "AND job_count>0 AND jobs_json NOT IN ('', '[]')")

RESULTS = []
GREETING = ""


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"   [{detail}]" if detail else ""))


def iso(days):
    return (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()


def week_key():
    return dt.datetime.utcnow().strftime("%Y-W%W")


# ── isolated copy of the live db, real cache kept, real users dropped ──

def open_live_copy():
    if not os.path.exists(LIVE_DB):
        raise SystemExit(f"no live database at {LIVE_DB}")
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    shutil.copyfile(LIVE_DB, tmp)
    db._DB_PATH = tmp
    db.init_db()
    with db._write_lock:
        with db._get_conn() as (conn, cur):
            for t in ("users", "email_queue", "visits", "saved_searches"):
                cur.execute(f"DELETE FROM {t}")
            conn.commit()
    return tmp


def ro():
    con = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ── discovery: every role/location below comes from the real cache ──

def discover():
    con = ro()
    d = {}
    row = con.execute(
        f"SELECT role, city, state, country FROM job_cache WHERE {BASE} "
        "AND city!='' AND state!='' AND country='in' ORDER BY job_count DESC LIMIT 1"
    ).fetchone()
    d["city"] = dict(row) if row else None

    # A role cached for a whole state, plus a real city in that state that has no
    # row for it — so the city rung must miss and the state rung must hit.
    d["state"] = None
    skip = d["city"]["role"] if d["city"] else ""
    for st in con.execute(
        f"SELECT role, state FROM job_cache WHERE {BASE} AND city='' AND state!='' "
        "AND country='in' AND role!=? ORDER BY job_count DESC LIMIT 40", (skip,)
    ).fetchall():
        alt = con.execute(
            f"SELECT DISTINCT city FROM job_cache WHERE {BASE} AND state=? AND city!='' "
            "AND role!=? AND LOWER(city)!=LOWER(?) LIMIT 1", (st["state"], st["role"], st["state"])
        ).fetchone()
        if not alt:
            continue
        hit = con.execute(
            f"SELECT 1 FROM job_cache WHERE {BASE} AND role=? AND city=?",
            (st["role"], alt["city"])
        ).fetchone()
        if not hit:
            d["state"] = ({"role": st["role"], "state": st["state"], "country": "in"}, alt["city"])
            break

    # A role cached in the home market together with a real city/state that has
    # no row for it and no state-only row either — so both scoped rungs miss and
    # only the country-wide union can answer.
    d["country"] = None
    for co in con.execute(
        f"SELECT role FROM job_cache WHERE {BASE} AND country='in' AND role!=? "
        "GROUP BY role ORDER BY COUNT(*) DESC LIMIT 40", (skip,)
    ).fetchall():
        alt = con.execute(
            f"SELECT city, state FROM job_cache WHERE {BASE} AND city!='' AND state!='' "
            f"AND role!=? AND city NOT IN (SELECT city FROM job_cache WHERE {BASE} "
            f"AND role=?) AND state NOT IN (SELECT state FROM job_cache WHERE {BASE} "
            f"AND role=? AND city='') LIMIT 1",
            (co["role"], co["role"], co["role"]),
        ).fetchone()
        if alt:
            d["country"] = ({"role": co["role"], "country": "in"},
                            {"city": alt["city"], "state": alt["state"]})
            break

    # A role cached in the home market but with nothing in a second market, so a
    # user over there resolves the role and still finds no jobs.
    other = con.execute(
        f"SELECT country FROM job_cache WHERE {BASE} AND country!='' AND country!='in' "
        "GROUP BY country HAVING COUNT(*) > 20 ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()
    d["foreign"] = None
    if other:
        miss = con.execute(
            f"SELECT role FROM job_cache WHERE {BASE} AND country='in' AND role NOT IN "
            f"(SELECT role FROM job_cache WHERE {BASE} AND country=?) "
            "GROUP BY role ORDER BY COUNT(*) DESC LIMIT 1", (other["country"],)
        ).fetchone()
        if miss:
            d["foreign"] = (miss["role"], other["country"])

    # The recipient's real display name, so live sends greet them as themselves,
    # plus a real country *name* (profiles store names; the cache is keyed on
    # ISO-2 codes).
    who = con.execute("SELECT name, country FROM users WHERE email=?",
                      (RECIPIENT,)).fetchone()
    d["greeting"] = ((who["name"] if who else "") or RECIPIENT.split("@")[0] or "there")
    global GREETING
    GREETING = d["greeting"]
    nm2 = con.execute("SELECT DISTINCT country FROM users WHERE country!='' LIMIT 1").fetchone()
    d["country_name"] = nm2["country"] if nm2 else ""
    d["countries"] = [r["country"] for r in con.execute(
        f"SELECT country FROM job_cache WHERE {BASE} AND country!='' "
        "GROUP BY country ORDER BY COUNT(*) DESC LIMIT 4").fetchall()]
    con.close()
    return d


def mangle(text, far=False):
    """Small edit (still resolvable) or one far enough past the fuzzy cutoff that
    nothing matches. The suffix is long relative to the role so the ratio falls
    below _ROLE_FUZZY_CUTOFF for any realistic role length."""
    if far:
        return f"{text} {'zqxjvkbnmqlwtr' * 2}"
    i = max(1, len(text) // 2)
    return text[:i] + text[i + 1:]


# ── fixtures: one users row (and optional visits) per case ──

def reset():
    with db._write_lock:
        with db._get_conn() as (conn, cur):
            for t in ("users", "email_queue", "visits"):
                cur.execute(f"DELETE FROM {t}")
            conn.commit()


def mk_user(email, days=20, position="", city="", state="", country="",
            resume="", opt_out=0, last_login="", visits=(), name=None):
    created = iso(days)
    with db._write_lock:
        with db._get_conn() as (conn, cur):
            cur.execute(
                "INSERT INTO users (email, name, company, position, city, state, country, "
                "resume_filename, created_at, updated_at, last_login, email_opt_out) "
                "VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (email, name if name is not None else GREETING, position, city, state,
                 country, resume, created, created, last_login, opt_out),
            )
            for i, (v_days, v_country, v_code) in enumerate(visits):
                cur.execute(
                    "INSERT INTO visits (visit_id, ip_address, user_email, created_at, "
                    "country, country_code) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"v{email}{i}", "1.2.3.4", email, iso(v_days), v_country, v_code),
                )
            conn.commit()


def run(enabled=True, per_run=None):
    """Run the real producer; returns the queued rows."""
    patches = [mock.patch.object(config, "ENGAGEMENT_ENABLED", enabled),
               mock.patch.object(config, "MAIL_QUEUE_ENABLED", True)]
    if per_run is not None:
        patches.append(mock.patch.object(config, "ENGAGEMENT_MAX_PER_RUN", per_run))
    for p in patches:
        p.start()
    try:
        scheduler.enqueue_engagement_emails()
    finally:
        for p in reversed(patches):
            p.stop()
    return queued()


def queued():
    with db._get_conn() as (conn, cur):
        cur.execute("SELECT recipient, subject, html_body, text_body, dedup_key "
                    "FROM email_queue ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


def run_new(enabled=True, per_run=None):
    """Run the producer and return only the rows this run added."""
    before = len(queued())
    run(enabled, per_run)
    return queued()[before:]


def only(label, cond, detail=""):
    """Run the producer, assert it produced exactly one email, hand it back."""
    rows = run_new()
    ok = len(rows) == 1 and cond(rows[0])
    check(label, ok, detail or f"{len(rows)} row(s)")
    return rows[0] if len(rows) == 1 else None


def seed_queue(recipient, key):
    with db._write_lock:
        with db._get_conn() as (conn, cur):
            cur.execute(
                "INSERT INTO email_queue (recipient, subject, html_body, text_body, "
                "dedup_key, status, attempts, created_at) "
                "VALUES (?, '', '', '', ?, 'pending', 0, ?)",
                (recipient, key, dt.datetime.utcnow().isoformat()),
            )
            conn.commit()


def bullets(row):
    """The listed jobs. The trailing '...and N more waiting' line is not a job."""
    return [l[2:].strip() for l in (row.get("text_body") or "").splitlines()
            if l.startswith("- ") and not l.startswith("- ...")]


GENERIC_SUBJECT = "JobAwn — Fresh roles are waiting for you"


def no_leak(row, *terms):
    """A generic email must not name a role, a location or a number."""
    blob = f"{row.get('subject','')} {row.get('text_body','')}"
    return not any(t and t.lower() in blob.lower() for t in terms)


def run_cases(d):
    # ── a role with cached jobs at each rung of the ladder ──
    if d["city"]:
        c = d["city"]
        reset(); mk_user("a@x.com", position=c["role"], city=c["city"], state=c["state"],
                         country=c["country"])
        r = only(f"city hit -> job list labelled with the city: {c['role']} / {c['city']}",
                 lambda x: c["role"] in x["subject"] and c["city"] in x["subject"]
                 and len(bullets(x)) == 3 and "Upload your resume" in x["text_body"])

        reset(); mk_user("a@x.com", position=c["role"], city=c["city"], state=c["state"],
                         country=c["country"], resume="cv.pdf")
        only("city hit + resume on file -> no resume hint",
             lambda x: "Upload your resume" not in x["text_body"] and len(bullets(x)) == 3)

        rows = run()
        r = rows[0] if rows else None
        if r:
            m = re.search(r"(\d+) fresh", r["subject"])
            check("headline count reconciles with the 3-job preview",
                  bool(m) and f"- ...and {int(m.group(1)) - 3} more waiting on JobAwn"
                  in r["text_body"],
                  m.group(1) if m else "no count")

    if d["state"]:
        (s, alt_city) = d["state"]
        reset(); mk_user("a@x.com", position=s["role"], city=alt_city, state=s["state"],
                         country=s["country"])
        only(f"city miss -> state rung names the state, not the city: {s['role']} / {s['state']}",
             lambda x: s["state"] in x["subject"] and alt_city not in x["subject"]
             and len(bullets(x)) == 3)

    if d["country"]:
        (co, elsewhere) = d["country"]
        reset(); mk_user("a@x.com", position=co["role"], city=elsewhere["city"],
                         state=elsewhere["state"], country=co["country"])
        only(f"city+state miss -> country rung claims no location: {co['role']}",
             lambda x: "near" not in x["subject"] and elsewhere["city"] not in x["subject"]
             and elsewhere["state"] not in x["subject"] and len(bullets(x)) == 3)

    if d["city"]:
        # ── a role, a location, but no market to look in ──
        c = d["city"]
        reset(); mk_user("a@x.com", position=c["role"], city=c["city"], state=c["state"],
                         country="")
        r = only("role + location but no country signal -> strictly generic",
                 lambda x: x["subject"] == GENERIC_SUBJECT and no_leak(x, c["role"], c["city"]))
        if r:
            check("  ...and it leaks neither the role nor the city",
                  no_leak(r, c["role"], c["city"], c["state"]))

    # ── role, no location ──
    if d["city"]:
        c = d["city"]
        reset(); mk_user("a@x.com", position=c["role"], city="", state="", country=c["country"])
        only(f"role only -> jobs with no location claim: {c['role']}",
             lambda x: c["role"] in x["subject"] and "near" not in x["subject"]
             and len(bullets(x)) == 3)

    if d["foreign"]:
        role, other = d["foreign"]
        reset(); mk_user("a@x.com", position=role, city="", state="", country=other)
        r = only(f"role cached elsewhere, none in this market -> generic: {role} / {other}",
                 lambda x: x["subject"] == GENERIC_SUBJECT)
        if r:
            check("  ...and the unresolved role is not named", no_leak(r, role))

    # ── location only / neither ──
    if d["city"]:
        c = d["city"]
        reset(); mk_user("a@x.com", position="", city=c["city"], state=c["state"], country="")
        r = only(f"location only -> location email, no role and no counts: {c['city']}",
                 lambda x: c["city"] in x["subject"] and c["role"] not in x["subject"]
                 and not bullets(x) and "fresh" not in x["subject"].lower())
        if r:
            check("  ...and it claims no job count", "fresh" not in r["subject"].lower())

    reset(); mk_user("a@x.com", position="", city="", state="", country="")
    only("neither role nor location -> generic",
         lambda x: x["subject"] == GENERIC_SUBJECT and not bullets(x))

    # ── role matching ──
    if d["city"]:
        c = d["city"]
        reset(); mk_user("a@x.com", position=mangle(c["role"]), city=c["city"],
                         state=c["state"], country=c["country"])
        only(f"small typo -> resolves to the canonical cached role: {c['role']}",
             lambda x: c["role"] in x["subject"] and len(bullets(x)) == 3)

        reset(); mk_user("a@x.com", position=mangle(c["role"], far=True), city=c["city"],
                         state=c["state"], country=c["country"])
        r = only("unrecognisable role -> generic, nothing invented",
                 lambda x: x["subject"] == GENERIC_SUBJECT and not bullets(x))
        if r:
            check("  ...and the raw role string is not echoed", no_leak(r, "zqxjvkbnmqlwtr"))

    # ── market resolution ──
    if d["city"] and d["country_name"]:
        c = d["city"]
        reset(); mk_user("a@x.com", position=c["role"], city=c["city"], state=c["state"],
                         country=d["country_name"])
        only(f"profile country as a name -> still matches the cache: {d['country_name']!r}",
             lambda x: len(bullets(x)) == 3)

    if d["city"] and d["countries"]:
        c = d["city"]
        code = d["countries"][0]
        reset(); mk_user("a@x.com", position=c["role"], city="", state="", country="",
                         visits=[(20, "", code)])
        only(f"no profile country -> taken from the last visit code: {code!r}",
             lambda x: len(bullets(x)) == 3)

        name = con_country_name(code)
        reset(); mk_user("a@x.com", position=c["role"], city="", state="", country="",
                         visits=[(20, name, "")])
        only(f"no profile country -> taken from the last visit name: {name!r}",
             lambda x: len(bullets(x)) == 3)

    # ── eligibility ──
    reset(); mk_user("a@x.com", opt_out=1)
    check("opted out -> no email", not run_new())

    reset(); mk_user("a@x.com", visits=[(0, "", "")])
    check("visited today -> no email", not run_new())

    reset(); mk_user("a@x.com", days=1)
    check("account younger than the minimum age -> no email", not run_new())

    reset(); mk_user("a@x.com")
    seed_queue("a@x.com", f"engage:{week_key()}:a@x.com")
    check("already emailed this week -> no second email", not run_new())

    reset(); mk_user("a@x.com")
    seed_queue("a@x.com", "engage:1999-W01:a@x.com")
    rows = run_new()
    check("last week's key does not block this week",
          len(rows) == 1 and rows[0]["dedup_key"] == f"engage:{week_key()}:a@x.com",
          rows[0]["dedup_key"] if rows else "none")

    reset()
    for i in range(5):
        mk_user(f"cap{i}@x.com")
    passes = [run_new(per_run=2) for _ in range(3)]
    got = [r["recipient"] for p in passes for r in p]
    check("per-pass cap advances through the dormant list, none lost",
          [len(p) for p in passes] == [2, 2, 1] and len(set(got)) == 5,
          "+".join(str(len(p)) for p in passes))

    reset(); mk_user("a@x.com")
    check("producer disabled -> nothing enqueued", not run_new(enabled=False))

    # ── unsubscribe signature ──
    reset(); mk_user("a@x.com")
    link = build_unsubscribe_url("a@x.com")
    check("unsubscribe link validates", validate_unsubscribe("a@x.com", link.split("s=")[1]))
    check("tampered signature rejected",
          not validate_unsubscribe("a@x.com", (link.split("s=")[1][:-2] + "xy")))
    check("signature is bound to the address",
          not validate_unsubscribe("b@x.com", link.split("s=")[1]))
    check("empty address -> empty link", build_unsubscribe_url("") == "")


def con_country_name(code):
    """The English name for a cache country code, from the app's own lookup."""
    try:
        from countrystatecity_countries import get_countries
        for c in get_countries():
            if (c.iso2 or "").lower() == code:
                return c.name
    except Exception:
        pass
    return code


def send_real(d):
    """One live email per outcome the matrix can produce, all from real cached
    roles and real postings, delivered to RECIPIENT."""
    from utils.smtp_sender import send_email
    print(f"\n--- sending live mail to {RECIPIENT} ---")
    out = []
    if d["city"]:
        c = d["city"]
        reset(); mk_user(RECIPIENT, position=c["role"], city=c["city"],
                         state=c["state"], country=c["country"])
        out.append((f"role+location, city hit ({c['role']} / {c['city']})", run()))
    if d["state"]:
        (s, alt) = d["state"]
        reset(); mk_user(RECIPIENT, position=s["role"], city=alt, state=s["state"],
                         country=s["country"])
        out.append((f"role+location, state rung ({s['role']} / {s['state']})", run()))
    if d["city"]:
        c = d["city"]
        reset(); mk_user(RECIPIENT, position=c["role"], city="", state="", country=c["country"])
        out.append((f"role only, no location claim ({c['role']})", run()))
    if d["city"]:
        c = d["city"]
        reset(); mk_user(RECIPIENT, position="", city=c["city"], state=c["state"])
        out.append((f"location only ({c['city']})", run()))
    if d["foreign"]:
        role, other = d["foreign"]
        reset(); mk_user(RECIPIENT, position=role, city="", state="", country=other)
        out.append((f"role with no cached jobs here -> generic ({role} / {other})", run()))
    reset(); mk_user(RECIPIENT)
    out.append(("neither role nor location -> generic", run()))

    for label, rows in out:
        if not rows:
            check(f"live send [{label}]", False, "nothing enqueued")
            continue
        row = rows[0]
        print(f"  [{label}]\n    {row['subject']}")
        ok = send_email(RECIPIENT, row["subject"], row["html_body"], row["text_body"] or None)
        check(f"live send [{label}]", ok, row["subject"][:52])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="also deliver real email per outcome")
    args = ap.parse_args()

    tmp = open_live_copy()
    d = discover()
    print(f"live db copied to {tmp} (live file untouched)")
    print("discovered from the real job_cache:")
    print(f"  city     : {d['city']}")
    print(f"  state    : {d['state']}")
    print(f"  country  : {d['country']}")
    print(f"  foreign  : {d['foreign']}")
    print(f"  country name in profiles: {d['country_name']!r}  cache markets: {d['countries']}\n")

    run_cases(d)
    if args.send:
        send_real(d)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
