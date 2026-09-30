import os
import re
import sys
import tempfile
import unittest
import contextlib
import datetime as dt
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import db  # noqa: E402
import scheduler  # noqa: E402
from emails import tokens  # noqa: E402
from emails import templates  # noqa: E402


class MailQueueDbTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db._DB_PATH = cls.tmp
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.tmp)
        except OSError:
            pass
        db._DB_PATH = os.path.join(os.path.dirname(os.path.abspath(db.__file__)), "job_agent.db")

    def tearDown(self):
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.execute("DELETE FROM email_queue")
                conn.commit()

    def test_enqueue_and_pending(self):
        db.enqueue_email("a@x.com", "S", "<p>h</p>", "h", dedup_key="k1")
        rows = db.get_pending_emails(10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["recipient"], "a@x.com")
        self.assertEqual(rows[0]["status"], "pending")
        self.assertEqual(rows[0]["dedup_key"], "k1")

    def test_dedup_blocks_second_insert(self):
        db.enqueue_email("a@x.com", "S", "<p>h</p>", "h", dedup_key="welcome:a@x.com")
        second = db.enqueue_email("a@x.com", "S", "<p>h</p>", "h", dedup_key="welcome:a@x.com")
        self.assertFalse(second)
        self.assertEqual(len(db.get_pending_emails(10)), 1)

    def test_empty_recipient_rejected(self):
        self.assertFalse(db.enqueue_email("", "S", "<p>h</p>"))
        self.assertEqual(db.get_pending_emails(10), [])

    def test_mark_sent(self):
        db.enqueue_email("a@x.com", "S", "<p>h</p>", dedup_key="k")
        row = db.get_pending_emails(1)[0]
        db.mark_email_sent(row["id"])
        self.assertEqual(db.get_pending_emails(10), [])
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT status, sent_at FROM email_queue WHERE id = ?", (row["id"],))
            r = cur.fetchone()
        self.assertEqual(r["status"], "sent")
        self.assertTrue(r["sent_at"])

    def test_three_failures_marks_failed(self):
        db.enqueue_email("a@x.com", "S", "<p>h</p>", dedup_key="k")
        row = db.get_pending_emails(1)[0]
        for _ in range(2):
            db.mark_email_failed(row["id"], "boom")
            self.assertEqual(len(db.get_pending_emails(10)), 1)
        db.mark_email_failed(row["id"], "boom")
        self.assertEqual(db.get_pending_emails(10), [])
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT status, attempts FROM email_queue WHERE id = ?", (row["id"],))
            r = cur.fetchone()
        self.assertEqual(r["status"], "failed")
        self.assertEqual(r["attempts"], 3)

    def test_drain_sends_and_marks_sent(self):
        db.enqueue_email("a@x.com", "S1", "<p>h</p>", dedup_key="a")
        db.enqueue_email("b@x.com", "S2", "<p>h</p>", dedup_key="b")
        with mock.patch("utils.smtp_sender.send_email", return_value=True):
            n = scheduler.run_mail_queue()
        self.assertEqual(n, 2)
        self.assertEqual(db.get_pending_emails(10), [])

    def test_drain_retries_failures(self):
        db.enqueue_email("a@x.com", "S", "<p>h</p>", dedup_key="a")
        with mock.patch("utils.smtp_sender.send_email", return_value=False) as send:
            scheduler.run_mail_queue()
            scheduler.run_mail_queue()
            self.assertEqual(len(db.get_pending_emails(10)), 1)
            scheduler.run_mail_queue()
        self.assertEqual(db.get_pending_emails(10), [])


class TemplateTestCase(unittest.TestCase):
    _ALLOWED = set(tokens.PALETTE.values())

    def _assert_safe(self, subject, html, text, campaign):
        self.assertIsInstance(subject, str)
        self.assertTrue(subject)
        self.assertTrue(html.startswith("<div"))
        self.assertTrue(text)
        self.assertTrue(campaign)
        # Every hex used in HTML must be in the palette.
        for m in re.findall(r"#[0-9a-fA-F]{6}", html):
            if m.upper() not in {v.upper() for v in self._ALLOWED}:
                self.fail(f"Non-palette color in template: {m}")
        # Exactly one primary CTA button.
        self.assertEqual(len(re.findall(r"background-color:#4f46e5", html)), 1,
                         "expected exactly one primary CTA")

    def test_welcome(self):
        subj, html, text, campaign = templates.build_welcome("Ammar")
        self.assertEqual(subj, "JobAwn — Welcome to JobAwn")
        self.assertIn("Hi Ammar", html)
        self._assert_safe(subj, html, text, campaign)

    def test_referral_requested(self):
        subj, html, text, campaign = templates.build_referral_requested(
            "Rahul", "Backend Engineer", "Cognizant", 87, "Hi, would love a referral!")
        self.assertEqual(subj, "JobAwn — Referral request: Backend Engineer")
        self.assertIn("Cognizant", html)
        self.assertIn("87/100", html)
        self.assertIn("Hi Rahul", html)
        self.assertTrue(html.startswith("<div"))
        self._assert_safe(subj, html, text, campaign)

    def test_referral_requested_escapes_html(self):
        subj, html, text, campaign = templates.build_referral_requested(
            "A&<B>", "<script>alert(1)</script>", "X", 40, "<b>msg</b>")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>msg</b>", html)
        self._assert_safe(subj, html, text, campaign)

    def test_referral_accepted(self):
        subj, html, text, campaign = templates.build_referral_accepted(
            "Meera", "Rahul", "Cognizant", "SDE", "https://linkedin.com/in/rahul")
        self.assertIn("accepted your referral request", subj)
        self.assertIn("https://linkedin.com/in/rahul", html)
        self.assertIn("Cognizant", html)
        self._assert_safe(subj, html, text, campaign)

    def test_referral_accepted_skips_empty_contact(self):
        subj, html, text, campaign = templates.build_referral_accepted("Meera", "", "", "", "")
        self.assertNotIn("View on LinkedIn", html)
        self._assert_safe(subj, html, text, campaign)

    def test_company_joined(self):
        subj, html, text, campaign = templates.build_company_joined("Meera", "Proofpoint")
        self.assertEqual(subj, "JobAwn — Someone from Proofpoint just joined")
        self.assertIn("Proofpoint", html)
        self.assertIn("Find a referrer at Proofpoint", html)
        self._assert_safe(subj, html, text, campaign)

    def test_confirm_reminder_receiver(self):
        subj, html, text, campaign = templates.build_confirm_reminder_receiver(
            "Rahul", "Meera", "Cognizant")
        self.assertEqual(subj, "JobAwn — Did you refer Meera at Cognizant?")
        self.assertIn("Meera", html)
        self.assertIn("Cognizant", html)
        self.assertIn("+10 JobAwn credits", html)
        self.assertIn("app#referrals", text)
        self._assert_safe(subj, html, text, campaign)

    def test_confirm_reminder_receiver_escapes_html(self):
        subj, html, text, campaign = templates.build_confirm_reminder_receiver(
            "Rahul", "<b>Bad</b>", "X&Y")
        self.assertNotIn("<b>Bad</b>", html)
        self.assertIn("X&amp;Y", html)
        self.assertNotIn("<script", html)
        self._assert_safe(subj, html, text, campaign)

    def test_confirm_reminder_receiver_empty_names_guarded(self):
        subj, html, text, campaign = templates.build_confirm_reminder_receiver("Rahul", "", "")
        self.assertIn("a seeker", html)
        self.assertIn("their company", html)
        self.assertEqual(subj, "JobAwn — Did you refer a seeker at their company?")
        self._assert_safe(subj, html, text, campaign)

    def test_confirm_reminder_sender(self):
        subj, html, text, campaign = templates.build_confirm_reminder_sender(
            "Meera", "Rahul", "Cognizant")
        self.assertEqual(subj, "JobAwn — Did Rahul refer you at Cognizant?")
        self.assertIn("Rahul", html)
        self.assertIn("Cognizant", html)
        self.assertIn("app#referrals", text)
        self._assert_safe(subj, html, text, campaign)

    def test_confirm_reminder_sender_escapes_html(self):
        subj, html, text, campaign = templates.build_confirm_reminder_sender(
            "Meera", "<i>R</i>", "A")
        self.assertNotIn("<i>R</i>", html)
        self._assert_safe(subj, html, text, campaign)

    def test_engagement(self):
        jobs = [
            {"title": "Senior Python Engineer", "company": "Acme", "location": "Remote"},
            {"title": "Backend Developer", "company": "Globex", "location": "New Delhi"},
        ]
        unsub = "https://jobawn.com/api/email/unsubscribe?email=a%40x.com&s=sig123"
        subj, html, text, campaign = templates.build_engagement(
            "Rahul", jobs, "Backend Developer", "New Delhi", 37, True, unsub)
        self.assertEqual(subj, "JobAwn — 37 fresh Backend Developer jobs near New Delhi")
        self.assertIn("37", html)
        self.assertIn("Senior Python Engineer", html)
        self.assertIn("Acme", html)
        self.assertIn("Backend Developer", html)
        self.assertIn("Unsubscribe", html)
        self.assertIn(unsub, html)
        self.assertNotIn("Upload your resume", html)
        self.assertIn("app", text)
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_resume_hint_when_missing(self):
        jobs = [{"title": "Backend Developer", "company": "Acme"}]
        subj, html, text, campaign = templates.build_engagement(
            "Rahul", jobs, "Backend Developer", "New Delhi", 12, False, "")
        self.assertIn("Upload your resume", html)
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_escapes_html(self):
        jobs = [{"title": "<script>alert(1)</script>", "company": "A&B", "location": "<b>X</b>"}]
        subj, html, text, campaign = templates.build_engagement(
            "R&B", jobs, "B&D", "N&D", 5, True, "")
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>X</b>", html)
        self.assertNotIn("<script", html)
        self.assertIn("&amp;", html)
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_no_unsubscribe_when_omitted(self):
        jobs = [{"title": "Backend Developer", "company": "Acme"}]
        subj, html, text, campaign = templates.build_engagement(
            "Rahul", jobs, "Backend Developer", "New Delhi", 3, True, "")
        self.assertNotIn("Unsubscribe", html)
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_subject_without_location(self):
        jobs = [{"title": "Backend Developer", "company": "Acme", "location": "Pune"}]
        unsub = "https://jobawn.com/api/email/unsubscribe?email=a%40x.com&s=s1"
        subj, html, text, campaign = templates.build_engagement(
            "Rahul", jobs, "Backend Developer", "", 12, True, unsub)
        self.assertEqual(subj, "JobAwn — 12 fresh Backend Developer jobs")
        # No location claim anywhere. ("near" alone would match CSS
        # linear-gradient, so assert on the actual copy markers instead.)
        for blob in (subj, html, text):
            self.assertNotIn("your area", blob.lower())
        self.assertNotIn("near", subj.lower())
        self.assertNotIn("near", text.lower())
        self.assertNotIn("near <strong>", html.lower())
        self.assertIn("We're keeping <strong>12 fresh Backend Developer jobs</strong> "
                      "warm for you.", html)
        # The count and the real per-job location are still there.
        self.assertIn("12", html)
        self.assertIn("Acme", html)
        self.assertIn("Pune", html)
        self.assertIn("Unsubscribe", html)
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_generic_subject_when_no_role(self):
        subj, html, text, campaign = templates.build_engagement(
            "Rahul", [], "", "", 0, True, "")
        self.assertEqual(subj, "JobAwn — Fresh roles are waiting for you")
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_location_prompt_names_the_location(self):
        unsub = "https://jobawn.com/api/email/unsubscribe?email=a%40x.com&s=sig123"
        subj, html, text, campaign = templates.build_engagement_location_prompt(
            "Meera", "Bengaluru, Karnataka", True, unsub)
        self.assertEqual(subj, "JobAwn — Find jobs in Bengaluru, Karnataka")
        self.assertIn("Bengaluru", html)
        self.assertIn(unsub, html)
        # No role and no invented counts: we never looked either up.
        self.assertNotIn("fresh", subj.lower())
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_location_prompt_resume_hint_and_escaping(self):
        subj, html, text, campaign = templates.build_engagement_location_prompt(
            "<Meera>", "Bengaluru", False, "")
        self.assertIn("Upload your resume", html)
        self.assertNotIn("<Meera>", html)
        self.assertNotIn("Unsubscribe", html)
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_fallback(self):
        unsub = "https://jobawn.com/api/email/unsubscribe?email=a%40x.com&s=sig123"
        subj, html, text, campaign = templates.build_engagement_fallback("Meera", True, unsub)
        self.assertEqual(subj, "JobAwn — Fresh roles are waiting for you")
        self.assertIn("Unsubscribe", html)
        self.assertIn(unsub, html)
        self.assertNotIn("Upload your resume", html)
        self._assert_safe(subj, html, text, campaign)

    def test_engagement_fallback_resume_hint_when_missing(self):
        subj, html, text, campaign = templates.build_engagement_fallback("Meera", False, "")
        self.assertIn("Upload your resume", html)
        self.assertNotIn("Unsubscribe", html)
        self._assert_safe(subj, html, text, campaign)


class EngagementSweepTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db._DB_PATH = cls.tmp
        db.init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls.tmp)
        except OSError:
            pass
        db._DB_PATH = os.path.join(os.path.dirname(os.path.abspath(db.__file__)), "job_agent.db")

    def tearDown(self):
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.execute("DELETE FROM email_queue")
                cur.execute("DELETE FROM saved_searches")
                cur.execute("DELETE FROM job_cache")
                cur.execute("DELETE FROM users")
                cur.execute("DELETE FROM visits")
                conn.commit()

    def _iso_days_ago(self, days):
        import datetime as dt
        return (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()

    def _add_user(self, email, created_days_ago, opt_out=0, last_login="",
                  position="", city="", country="", state=""):
        created = self._iso_days_ago(created_days_ago)
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.execute(
                    "INSERT INTO users (email, name, company, position, city, state, country, "
                    "created_at, updated_at, last_login, email_opt_out) "
                    "VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (email, "U", position, city, state, country, created, created,
                     last_login, opt_out),
                )
                conn.commit()

    def _add_visit(self, email, days_ago, country="", country_code=""):
        ts = self._iso_days_ago(days_ago)
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.execute(
                    "INSERT INTO visits (visit_id, ip_address, user_email, created_at, "
                    "country, country_code) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"v{email}{days_ago}", "1.2.3.4", email, ts, country, country_code),
                )
                conn.commit()

    def _add_cache_row(self, role, city="", state="", country="in", site="indeed",
                       jobs=None):
        import json
        jobs = jobs or [{"title": "Backend Engineer", "company": "Acme",
                         "url": "https://x/1", "location": city or "India", "posted": "2d"}]
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.execute(
                    "INSERT OR REPLACE INTO job_cache (role, site, city, state, country, "
                    "internship_mode, hours_old, is_remote, job_count, jobs_json, scraped_at) "
                    "VALUES (?, ?, ?, ?, ?, 0, 168, 0, ?, ?, ?)",
                    (role, site, city, state, country, len(jobs), json.dumps(jobs),
                     dt.datetime.utcnow().isoformat()),
                )
                conn.commit()

    def _add_saved_search(self, email, role, location):
        import json
        with db._write_lock:
            with db._get_conn() as (conn, cur):
                cur.execute(
                    "INSERT OR REPLACE INTO saved_searches (id, email, name, sites, keywords, "
                    "roles, location, internship_mode, interval_hours, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 168, ?)",
                    (f"ss-{email}", email, "s", json.dumps(["linkedin"]), json.dumps([]),
                     json.dumps([role]), location, dt.datetime.utcnow().isoformat()),
                )
                conn.commit()

    def _pending_engagement(self):
        with db._get_conn() as (conn, cur):
            cur.execute("SELECT recipient, dedup_key, subject, html_body, text_body "
                        "FROM email_queue WHERE dedup_key LIKE 'engage:%' ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    def _run_sweep(self, max_per_run=None):
        patches = [mock.patch("config.ENGAGEMENT_ENABLED", True)]
        if max_per_run is not None:
            patches.append(mock.patch("config.ENGAGEMENT_MAX_PER_RUN", max_per_run))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            from scheduler import enqueue_engagement_emails
            return enqueue_engagement_emails()

    def test_opt_out_migration_and_flag(self):
        with db._get_conn() as (conn, cur):
            cur.execute("PRAGMA table_info(users)")
            cols = {r["name"] for r in cur.fetchall()}
        self.assertIn("email_opt_out", cols)
        self._add_user("flag@x.com", 10)
        db.set_user_email_opt_out("flag@x.com", True)
        self.assertEqual(db.get_user("flag@x.com")["email_opt_out"], 1)
        db.set_user_email_opt_out("flag@x.com", False)
        self.assertEqual(db.get_user("flag@x.com")["email_opt_out"], 0)

    def test_engagement_sweep_enqueues_only_dormant(self):
        self._add_user("dormant@x.com", 20)
        self._add_user("active@x.com", 20)
        self._add_visit("active@x.com", 0)
        self._add_user("optedout@x.com", 20, opt_out=1)
        self._add_user("toonew@x.com", 1)
        self._add_user("recentlogin@x.com", 20, last_login=self._iso_days_ago(0))
        self.assertEqual(self._run_sweep(), 1)
        rows = self._pending_engagement()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["recipient"], "dormant@x.com")
        self.assertIn("Fresh roles are waiting", rows[0]["subject"])

    def test_engagement_sweep_dedup_same_week(self):
        self._add_user("dormant@x.com", 20)
        self.assertEqual(self._run_sweep(), 1)
        self.assertEqual(self._run_sweep(), 0)
        self.assertEqual(len(self._pending_engagement()), 1)

    def test_engagement_sweep_respects_per_run_limit(self):
        for i in range(5):
            self._add_user(f"d{i}@x.com", 20)
        self.assertEqual(self._run_sweep(max_per_run=3), 3)
        self.assertEqual(self._run_sweep(max_per_run=3), 2)
        rows = self._pending_engagement()
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({r["recipient"] for r in rows}), 5)

    def test_sweep_sends_location_email_when_no_role_on_file(self):
        self._add_user("loc@x.com", 20, position="", city="Bengaluru",
                       state="Karnataka", country="in")
        self._add_cache_row("Backend Developer", city="Bengaluru", state="Karnataka", country="in")
        self.assertEqual(self._run_sweep(), 1)
        row = self._pending_engagement()[0]
        self.assertEqual(row["subject"], "JobAwn — Find jobs in Bengaluru, Karnataka")
        # A cached role for that location must not leak in: the user named no role.
        self.assertNotIn("Backend Developer", row["subject"] + row["text_body"])

    def test_sweep_falls_back_to_generic_when_role_has_no_cached_jobs(self):
        self._add_user("noluck@x.com", 20, position="Backend Developer",
                       city="Bengaluru", state="Karnataka", country="in")
        self._add_cache_row("Software Engineer", city="Bengaluru", state="Karnataka", country="in")
        self.assertEqual(self._run_sweep(), 1)
        row = self._pending_engagement()[0]
        self.assertEqual(row["subject"], "JobAwn — Fresh roles are waiting for you")
        blob = row["subject"] + row["text_body"]
        self.assertNotIn("Backend Developer", blob)
        self.assertNotIn("Bengaluru", blob)

    def test_country_from_profile_name_is_normalized_to_code(self):
        # users.country stores a name ("India") but job_cache is keyed on the
        # ISO-2 code ("in") — without this the country scope never matches.
        from scheduler import _engagement_country
        self._add_user("in@x.com", 20, country="India")
        self.assertEqual(_engagement_country(db.get_user("in@x.com")), "in")
        self._add_user("code@x.com", 20, country="US")
        self.assertEqual(_engagement_country(db.get_user("code@x.com")), "us")
        self._add_user("raw@x.com", 20, country="in")
        self.assertEqual(_engagement_country(db.get_user("raw@x.com")), "in")

    def test_country_falls_back_to_last_visit(self):
        from scheduler import _engagement_country
        self._add_user("geo@x.com", 20, country="")
        self._add_visit("geo@x.com", 20, country="India", country_code="in")
        user = db.get_user("geo@x.com")
        user["visit_country_code"] = "in"
        self.assertEqual(_engagement_country(user), "in")

    def test_country_falls_back_to_visit_country_name(self):
        # Most visit rows predate visits.country_code and only carry the name.
        from scheduler import _engagement_country
        self._add_user("name@x.com", 20, country="")
        self._add_visit("name@x.com", 20, country="India", country_code="")
        cutoff = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat()
        hits = {u["email"]: u for u in db.get_engagement_recipients(cutoff, 3, 10)}
        self.assertEqual(hits["name@x.com"]["visit_country_code"], None)
        self.assertEqual(_engagement_country(hits["name@x.com"]), "in")

    def test_country_unknown_returns_empty_and_anchor_is_dropped(self):
        from scheduler import _engagement_anchor
        self._add_user("nogeo@x.com", 20, position="Backend Developer", country="")
        self._add_cache_row("Backend Developer", city="", state="", country="in")
        # No profile country and no visit country -> no market to search, so we
        # don't guess one and the user gets the generic fallback.
        self.assertIsNone(self._anchor(db.get_user("nogeo@x.com"))[0])

    def test_engagement_recipients_expose_visit_country(self):
        self._add_user("geo@x.com", 20, country="")
        self._add_visit("geo@x.com", 20, country="India", country_code="in")
        cutoff = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat()
        hits = {u["email"]: u for u in db.get_engagement_recipients(cutoff, 3, 10)}
        self.assertEqual(hits["geo@x.com"]["visit_country_code"], "in")

    def test_engagement_recipients_helper(self):
        self._add_user("dormant@x.com", 20)
        self._add_user("active@x.com", 20)
        self._add_visit("active@x.com", 0)
        self._add_user("optout@x.com", 20, opt_out=1)
        self._add_user("toonew@x.com", 1)
        import datetime as dt
        cutoff = (dt.datetime.utcnow() - dt.timedelta(days=7)).isoformat()
        hits = db.get_engagement_recipients(cutoff, min_age_days=3, limit=10)
        self.assertEqual([u["email"] for u in hits], ["dormant@x.com"])

    def _anchor(self, user):
        from scheduler import _cached_role_vocab, _engagement_anchor
        return _engagement_anchor(user, _cached_role_vocab(168))

    def test_anchor_ignores_saved_search_and_uses_the_profile(self):
        # The profile is the only source now: a saved search must not override it.
        self._add_user("ss@x.com", 20, position="Backend Developer",
                       city="New Delhi", state="Delhi", country="in")
        self._add_saved_search("ss@x.com", "Data Engineer", "Bangalore, Karnataka")
        self._add_cache_row("Backend Developer", city="New Delhi", state="Delhi", country="in")
        self._add_cache_row("Data Engineer", city="Bangalore", state="Karnataka", country="in")
        role, label, city, state, country = self._anchor(db.get_user("ss@x.com"))
        self.assertEqual((role, label, city, state, country),
                         ("Backend Developer", "New Delhi", "New Delhi", "Delhi", "in"))

    def test_anchor_keeps_location_label_when_role_is_absent(self):
        # The label has to survive with no role: that is what drives the
        # location-only email.
        self._add_user("loc@x.com", 20, position="", city="Bengaluru",
                       state="Karnataka", country="in")
        self._add_cache_row("Backend Developer", city="Bengaluru", state="Karnataka", country="in")
        role, label, city, state, _c = self._anchor(db.get_user("loc@x.com"))
        self.assertIsNone(role)
        self.assertEqual((label, city, state), ("Bengaluru, Karnataka", "Bengaluru", "Karnataka"))

    def test_anchor_from_profile_avoids_duplicated_location(self):
        self._add_user("ny@x.com", 20, position="Backend Developer",
                       city="New Delhi", state="Delhi", country="in")
        self._add_cache_row("Backend Developer", city="New Delhi", state="Delhi", country="in")
        role, label, city, state, _country = self._anchor(db.get_user("ny@x.com"))
        self.assertEqual((role, label, city, state), ("Backend Developer", "New Delhi", "New Delhi", "Delhi"))

    def test_anchor_absent_without_saved_search_or_position(self):
        self._add_user("bare@x.com", 20, position="")
        self._add_cache_row("Backend Developer", city="", state="", country="in")
        self.assertIsNone(self._anchor(db.get_user("bare@x.com"))[0])

    def test_anchor_absent_when_role_cannot_be_resolved(self):
        self._add_user("fresh@x.com", 20, position="Fresher", country="in")
        self._add_cache_row("Backend Developer", city="", state="", country="in")
        self.assertIsNone(self._anchor(db.get_user("fresh@x.com"))[0])

    def test_anchor_resolves_dirty_profile_role(self):
        self._add_user("typo@x.com", 20, position="Software Enginner", country="in")
        self._add_cache_row("Software Engineer", city="", state="", country="in")
        # The canonical cached role is used, never the user's spelling.
        self.assertEqual(self._anchor(db.get_user("typo@x.com"))[0], "Software Engineer")

    def test_role_resolution_real_profile_strings(self):
        """Regression set: the free-text positions real users actually have.
        job_cache.role is BINARY-collated, so every row here fails a plain
        `role = position` lookup for a different reason."""
        from scheduler import _norm_role, _resolve_role

        def make_vocab(roles):
            return ({r.lower(): r for r in roles},
                    [(_norm_role(r), r) for r in roles])

        vocab = make_vocab([
            "Software Engineer", "Software Developer", "AI Engineer",
            "Backend Developer", "Node.js Developer", "Business Analyst",
            "Business Development Representative", "Test Automation Engineer",
        ])
        cases = {
            "Software Engineer": "Software Engineer",            # exact
            "Software developer": "Software Developer",            # case
            "Ai Engineer": "AI Engineer",                          # case + acronym
            "Backend Developer Intern": "Backend Developer",      # qualifier
            "Software Enginner": "Software Engineer",             # typo
            "Node js developer": "Node.js Developer",             # punctuation
            "Business Analyst": "Business Analyst",              # exact
            "Fresher": "",                                        # not a role we cache
            "Tester": "",                                         # too far from any role
            "": "",
        }
        for raw, expected in cases.items():
            with self.subTest(position=raw):
                self.assertEqual(_resolve_role(raw, vocab), expected)
        self.assertEqual(_resolve_role("Backend Developer", ({}, [])), "")

    def test_engagement_fresh_jobs_city_scope_labels_the_city(self):
        from scheduler import _engagement_fresh_jobs
        self._add_user("pune@x.com", 20, position="Backend Developer",
                       city="Pune", state="Maharashtra", country="in")
        self._add_cache_row("Backend Developer", city="Pune", state="Maharashtra", country="in")
        anchor = self._anchor(db.get_user("pune@x.com"))
        jobs, label = _engagement_fresh_jobs(anchor, 168, 30)
        self.assertTrue(jobs)
        self.assertEqual(label, "Pune, Maharashtra")

    def test_engagement_fresh_jobs_state_scope_labels_the_state(self):
        from scheduler import _engagement_fresh_jobs
        self._add_user("bang@x.com", 20, position="Backend Developer",
                       city="Bangalore", state="Karnataka", country="in")
        # Only the state row exists (the cache grid stores "Bengaluru", not "Bangalore").
        self._add_cache_row("Backend Developer", city="", state="Karnataka", country="in")
        anchor = self._anchor(db.get_user("bang@x.com"))
        jobs, label = _engagement_fresh_jobs(anchor, 168, 30)
        self.assertTrue(jobs)
        self.assertEqual(label, "Karnataka")

    def test_engagement_fresh_jobs_country_scope_has_no_location(self):
        from scheduler import _engagement_fresh_jobs
        self._add_user("wide@x.com", 20, position="Backend Developer",
                       city="Pune", state="Maharashtra", country="in")
        self._add_cache_row("Backend Developer", city="", state="", country="in")
        anchor = self._anchor(db.get_user("wide@x.com"))
        jobs, label = _engagement_fresh_jobs(anchor, 168, 30)
        self.assertTrue(jobs)
        self.assertEqual(label, "")

    def test_engagement_fresh_jobs_no_scope_match_returns_nothing(self):
        from scheduler import _engagement_fresh_jobs
        self._add_user("none@x.com", 20, position="Backend Developer",
                       city="Pune", state="Maharashtra", country="in")
        self._add_cache_row("Software Engineer", city="", state="", country="in")
        anchor = self._anchor(db.get_user("none@x.com"))
        self.assertEqual(_engagement_fresh_jobs(anchor, 168, 30), ([], ""))

    def test_engagement_fresh_jobs_no_location_set_uses_country_scope(self):
        from scheduler import _engagement_fresh_jobs
        self._add_user("noloc@x.com", 20, position="Backend Developer", country="in")
        self._add_cache_row("Backend Developer", city="", state="", country="in")
        anchor = self._anchor(db.get_user("noloc@x.com"))
        self.assertEqual((anchor[2], anchor[3]), ("", ""))
        jobs, label = _engagement_fresh_jobs(anchor, 168, 30)
        self.assertTrue(jobs)
        self.assertEqual(label, "")

    def test_sweep_subject_uses_no_location_when_only_country_cached(self):
        self._add_user("dormant-noloc@x.com", 20, position="Backend Developer", country="in")
        self._add_cache_row("Backend Developer", city="", state="", country="in")
        self.assertEqual(self._run_sweep(), 1)
        rows = self._pending_engagement()
        self.assertEqual(rows[0]["subject"], "JobAwn — 1 fresh Backend Developer jobs")
        self.assertNotIn("near", rows[0]["subject"].lower())


if __name__ == "__main__":
    unittest.main()