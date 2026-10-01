from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ForumReplyUiTests(unittest.TestCase):
    def test_topic_template_has_explicit_reply_states(self) -> None:
        text = (ROOT / "templates" / "ecosystem" / "forum_topic.html").read_text(encoding="utf-8")
        self.assertIn("{% elif viewer %}", text)
        self.assertIn("Antwort veröffentlichen", text)
        self.assertIn("Zum Antworten benötigst du ein bestätigtes Mycelia-Konto.", text)
        self.assertIn("Dieses Thema ist geschlossen", text)
        self.assertNotIn("{% if shop_user and not topic.locked %}", text)

    def test_forum_list_does_not_depend_on_foreign_blueprint_context(self) -> None:
        text = (ROOT / "templates" / "ecosystem" / "forum.html").read_text(encoding="utf-8")
        self.assertIn("{% if viewer %}", text)
        self.assertIn("Anmelden, um ein Thema zu erstellen", text)
        self.assertNotIn("{% if shop_user %}", text)

    def test_ecosystem_routes_pass_viewer_to_forum_templates(self) -> None:
        text = (ROOT / "cms" / "modules" / "ecosystem" / "routes.py").read_text(encoding="utf-8")
        self.assertIn("viewer=current_user()", text)
        self.assertIn("viewer=user", text)

    def test_login_preserves_only_safe_local_next_target(self) -> None:
        routes = (ROOT / "cms" / "modules" / "webshop" / "routes.py").read_text(encoding="utf-8")
        login = (ROOT / "templates" / "webshop" / "user_login.html").read_text(encoding="utf-8")
        self.assertIn("def safe_next_url", routes)
        self.assertIn('value.startswith("//")', routes)
        self.assertIn('name="next"', login)


if __name__ == "__main__":
    unittest.main()
