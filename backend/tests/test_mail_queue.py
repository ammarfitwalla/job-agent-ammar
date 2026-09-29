import os
import re
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()