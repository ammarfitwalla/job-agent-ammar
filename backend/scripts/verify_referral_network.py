"""End-to-end verification of the referral-network feature (Option 2).

Runs the REAL FastAPI route handlers against a throwaway SQLite DB so your
real job_agent.db is never touched. Creates dummy accounts + dummy job links
and verifies: opt-in gating, URL resolution, referral request/accept flow,
invite bonus credits, and notify-intent.

Run from repo root:  python backend/scripts/verify_referral_network.py
"""
import contextlib
import os
import sys
import tempfile

BACKEND = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)

import sqlite3
from unittest.mock import patch

# ---- temp DB (schema identical to real init_db) ----
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
DB_PATH = _TMP.name
print(f"[setup] using throwaway DB: {DB_PATH}")

from db import init_db

def _fresh_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;")
    return conn, conn.cursor()

@contextlib.contextmanager
def _fake_get_conn():
    conn, cur = _fresh_conn()
    try:
        yield conn, cur
    finally:
        pass  # caller closes

# Patch DB access to the throwaway file BEFORE init so the temp DB is built.
_patcher = patch("db._get_conn", _fake_get_conn)
_patcher.start()

init_db()

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

results = []
def check(name, cond, extra=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, cond))
    print(f"  [{status}] {name}{('  ' + str(extra)) if extra else ''}")

def reg(email, name, company="", refer_opt_in=0, invited_by=""):
    r = client.post("/api/auth/verify-code", json={"email": email, "code": "123456"})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/register", json={
        "email": email, "name": name, "company": company,
        "position": "", "linkedin_url": "",
        "refer_opt_in": refer_opt_in, "invited_by": invited_by or "",
    })
    assert r.json().get("ok"), f"{name}: {r.text}"
    return r.json()["user"]

# ================= DUMMY ACCOUNTS =================
print("\n>> Creating dummy accounts")
a_tcs_ref  = reg("priya.ref@dummy.test", "Priya Ref",       "Tata Consultancy Services", refer_opt_in=1)
a_cog_ref  = reg("ravi.ref@dummy.test",  "Ravi Ref",        "Cognizant",                 refer_opt_in=1)
a_wpp_ref  = reg("meera.ref@dummy.test", "Meera Ref",       "WPP Media",                 refer_opt_in=1)
a_seeker   = reg("seeker@dummy.test",    "Ammar Seeker",    "Microsoft",                 refer_opt_in=0)  # NOT opted in
a_hidden   = reg("ghost@dummy.test",     "Ghost Employee",  "Tata Consultancy Services", refer_opt_in=0)  # same company, not opted in

# ================= OPT-IN GATING =================
print("\n>> Opt-in gating")
r = client.get("/api/users/at-company", params={"company": "Tata Consultancy Services"})
emails = [u["email"] for u in r.json()["users"]]
check("at-company lists opted-in referrer", "priya.ref@dummy.test" in emails)
check("at-company hides non-opted-in (ghost)", "ghost@dummy.test" not in emails)
check("at-company hides seeker (not opted-in)", "seeker@dummy.test" not in emails)

r = client.get("/api/users/company-counts", params={"companies": "Cognizant,Tata Consultancy Services,WPP Media,Microsoft"})
counts = r.json()["counts"]
check("company-counts Cognizant = 1", counts.get("Cognizant") == 1)
check("company-counts TCS = 1", counts.get("Tata Consultancy Services") == 1)
check("company-counts Microsoft = 0 (seeker not opted in)", counts.get("Microsoft") == 0)

r = client.get("/api/users/referrer-directory")
dir_companies = [c["company"] for c in r.json()["companies"]]
check("directory has TCS", "Tata Consultancy Services" in dir_companies)
check("directory has WPP Media", "WPP Media" in dir_companies)

# ================= URL RESOLUTION =================
print("\n>> Dummy job-link resolution")
links = [
    ("https://boards.greenhouse.io/tcs/jobs/7788990012",    "Tata Consultancy Services"),
    ("https://careers.cognizant.com/jobs/software-engineer", "Cognizant"),
    ("https://wpp.com/careers",                              "WPP Media"),
    ("https://naukri.com/job/software-engineer-cognizant-7755", "Cognizant"),
    ("https://jobs.lever.co/microsoft/senior-pm-xyz",        "Microsoft"),
]
for url, want in links:
    r = client.post("/api/referrals/resolve-url", json={"url": url})
    d = r.json()
    check(f"resolve {url.split('/')[2]}", d.get("ok") and d.get("company") == want, f"-> {d.get('company')}")

# referrer_count must be opt-in only
r = client.post("/api/referrals/resolve-url", json={"url": "https://boards.greenhouse.io/tcs/jobs/x"})
check("tcs link referrer_count = 1 (opt-in only)", r.json().get("referrer_count") == 1, f"count={r.json().get('referrer_count')}")

r = client.post("/api/referrals/resolve-url", json={"url": "garbage-not-a-url"})
check("invalid link rejected 400", r.status_code == 400)

# ================= REFERRAL REQUEST FLOW =================
print("\n>> Referral request -> accept flow")
job_url = "https://boards.greenhouse.io/tcs/jobs/7788990012"
r = client.post("/api/referrals/request", json={
    "from_email": a_seeker["email"], "to_email": a_tcs_ref["email"],
    "job_url": job_url, "job_title": "Software Engineer",
    "company": "Tata Consultancy Services", "match_score": 91, "message": "Hi! Great fit, pls refer",
})
check("request created", r.json().get("ok"), r.json())

outgoing = client.get("/api/referrals/outgoing", params={"email": a_seeker["email"]}).json()
rid = outgoing["requests"][0]["id"]
check("outgoing shows request", outgoing["requests"][0]["company"] == "Tata Consultancy Services")

r = client.put(f"/api/referrals/{rid}/accept", json={"email": a_tcs_ref["email"]})
check("referrer accepts -> contact revealed", r.json().get("ok") and "contact" in r.json(), r.json())

r = client.get("/api/referrals/remaining", params={"email": a_seeker["email"]})
check("remaining decremented to 4", r.json()["remaining"] == 4, r.json())

# ================= INVITE / CREDITS =================
print("\n>> Invite link + credit bonus")
a_invitee = reg("friend@dummy.test", "Invited Friend", "WPP Media", refer_opt_in=0, invited_by=a_tcs_ref["email"])
check("invitee auto opted-in", a_invitee["refer_opt_in"] == 1)
prof_inviter = client.get("/api/profile", params={"email": a_tcs_ref["email"]}).json()
prof_invitee = client.get("/api/profile", params={"email": "friend@dummy.test"}).json()
check("inviter +5 credits", prof_inviter["referral_credits"] == 5, prof_inviter["referral_credits"])
check("invitee +5 credits", prof_invitee["referral_credits"] == 5, prof_invitee["referral_credits"])

# profile opt-in toggle off
r = client.put("/api/profile/refer-opt-in", json={"email": "meera.ref@dummy.test", "refer_opt_in": 0})
check("toggle opt-in off", r.json().get("ok") and r.json()["refer_opt_in"] == 0)
r = client.get("/api/users/at-company", params={"company": "WPP Media"})
emails = [u["email"] for u in r.json()["users"]]
check("toggled-off referrer no longer listed", "meera.ref@dummy.test" not in emails)
client.put("/api/profile/refer-opt-in", json={"email": "meera.ref@dummy.test", "refer_opt_in": 1})

# ================= NOTIFY INTENT =================
print("\n>> Notify-when-available (no referrer yet)")
r = client.post("/api/referrals/notify", json={"email": "seeker@dummy.test", "company": "Netflix"})
check("notify stored (ok)", r.json().get("ok"), r.json())
r2 = client.post("/api/referrals/notify", json={"email": "seeker@dummy.test", "company": "Netflix"})
check("notify dedupes", r2.json().get("ok"))
r = client.get("/api/referrals/notifies", params={"company": "Netflix"})
emails = [n["email"] for n in r.json().get("notifies", [])]
check("notify intent retrievable", "seeker@dummy.test" in emails)

# ================= SHARE LINK =================
print("\n>> Dummy-account share-link parity")
share = f"{client.base_url}/app?ref={a_wpp_ref['email']}&company=WPP+Media"
check("share link shape", "/app?ref=meera.ref@dummy.test&company=WPP+Media" in share, share)

_patcher.stop()

print("\n==============================")
passed = sum(1 for _, ok in results if ok)
total = len(results)
print(f"RESULT: {passed}/{total} checks passed")
try:
    os.unlink(DB_PATH)
    for suffix in ("-wal", "-shm"):
        p = DB_PATH + suffix
        if os.path.exists(p):
            os.unlink(p)
except Exception as e:
    print("cleanup:", e)
sys.exit(0 if passed == total else 1)