"""admin.js is loaded as type="module", so top-level functions are not global.
Every inline on*="fn()" handler in admin.html must therefore be attached to
window explicitly, or the button silently does nothing."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class AdminInlineHandlerWiringTestCase(unittest.TestCase):
    def test_every_inline_handler_is_exported_on_window(self):
        html = (ROOT / "frontend" / "admin.html").read_text(encoding="utf-8")
        js = (ROOT / "frontend" / "js" / "admin.js").read_text(encoding="utf-8")

        handlers = set(re.findall(r'on(?:click|change|input)="([A-Za-z_$][\w$]*)\(', html))
        exported = set(re.findall(r'window\.([A-Za-z_$][\w$]*)\s*=', js))

        missing = sorted(handlers - exported)
        self.assertEqual(
            missing,
            [],
            f"inline handlers not attached to window (dead buttons): {missing}",
        )


if __name__ == "__main__":
    unittest.main()
