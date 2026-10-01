from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TemplateHardeningTests(unittest.TestCase):
    def test_public_renderer_never_marks_editor_content_safe(self) -> None:
        public = (ROOT / "templates" / "public_page.html").read_text(encoding="utf-8")
        self.assertNotIn("|safe", public)
        self.assertIn("render_richtext(richtext_doc(page.body", public)
        self.assertNotIn("|safe", (ROOT / "templates" / "richtext" / "view.html").read_text(encoding="utf-8"))

    def test_no_inline_event_handlers(self) -> None:
        pattern = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
        for path in (ROOT / "templates").rglob("*.html"):
            self.assertIsNone(pattern.search(path.read_text(encoding="utf-8")), path.name)

    def test_all_post_forms_contain_csrf(self) -> None:
        for path in (ROOT / "templates").rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            for form in re.findall(r"<form\b[^>]*method=\"post\"[^>]*>(.*?)</form>", text, flags=re.I | re.S):
                self.assertIn('name="csrf_token"', form, path.name)


if __name__ == "__main__":
    unittest.main()
