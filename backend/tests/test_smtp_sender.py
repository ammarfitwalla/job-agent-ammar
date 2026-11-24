"""Guards for the SMTP senders: an empty recipient must never reach the
provider (it produced SendCoreX 400 MISSING_TO / SMTP 552 spam) and attachment
sends must not use the SendCoreX API path, which silently drops attachments."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from utils import smtp_sender  # noqa: E402


class EmptyRecipientTestCase(unittest.TestCase):
    def test_send_email_skips_empty_recipient(self):
        with mock.patch.object(smtp_sender, "_smtp_settings") as settings:
            self.assertFalse(smtp_sender.send_email("", "S", "<p>x</p>"))
            self.assertFalse(smtp_sender.send_email("   ", "S", "<p>x</p>"))
        settings.assert_not_called()

    def test_attachment_skips_empty_recipient(self):
        with mock.patch.object(smtp_sender, "_smtp_settings") as settings:
            self.assertFalse(
                smtp_sender.send_email_with_attachment(
                    "", "S", "<p>x</p>", "missing.bin", "x.bin"
                )
            )
        settings.assert_not_called()


class AttachmentPathTestCase(unittest.TestCase):
    def test_attachment_never_uses_sendcorex_api(self):
        """The API path ignores file_path, so a successful API call would email
        no backup at all. Attachments must go straight to SMTP."""
        scx = mock.Mock(return_value=True)
        with mock.patch("config.EMAIL_PROVIDER", "sendcorex_api"), \
             mock.patch("utils.sendcorex_api.send", scx), \
             mock.patch.object(smtp_sender, "_smtp_settings", return_value=None):
            ok = smtp_sender.send_email_with_attachment(
                "a@x.com", "S", "<p>x</p>", "missing.bin", "x.bin"
            )
        self.assertFalse(ok)
        scx.assert_not_called()


if __name__ == "__main__":
    unittest.main()
