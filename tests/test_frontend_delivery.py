import json
import tempfile
import unittest
from pathlib import Path

from nolthira.core.agent import _is_website_build_request, _nextjs_frontend_delivery_issues


class WebsiteBuildIntentTests(unittest.TestCase):
    def test_detects_direct_english_website_build_requests(self):
        self.assertTrue(_is_website_build_request("Build a website for my portfolio"))
        self.assertTrue(_is_website_build_request("Create a landing page for the product"))

    def test_detects_direct_indonesian_website_build_requests(self):
        self.assertTrue(_is_website_build_request("Buatkan aku website store digital"))
        self.assertTrue(_is_website_build_request("Tolong bikin web app dashboard"))

    def test_does_not_treat_prompt_writing_or_how_to_questions_as_build_orders(self):
        self.assertFalse(_is_website_build_request("Buatkan prompt untuk membuat website store"))
        self.assertFalse(_is_website_build_request("How do I build a website?"))

    def test_flags_unmodified_create_next_app_homepage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0", "react": "19.0.0"}}),
                encoding="utf-8",
            )
            (root / "app").mkdir()
            (root / "app" / "page.tsx").write_text(
                "export default function Home() { return <main>"
                "To get started, edit the page.tsx file. "
                "Looking for a starting point or more instructions? "
                "</main>; }",
                encoding="utf-8",
            )

            issues = _nextjs_frontend_delivery_issues(root)

            self.assertEqual(len(issues), 1)
            self.assertIn("app/page.tsx", issues[0])
            self.assertIn("starter screen", issues[0])

    def test_accepts_a_replaced_nextjs_homepage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )
            (root / "src" / "app").mkdir(parents=True)
            (root / "src" / "app" / "page.tsx").write_text(
                "export default function Home() { return <main><h1>Digital Store</h1>"
                "<section>Featured products</section></main>; }",
                encoding="utf-8",
            )

            self.assertEqual(_nextjs_frontend_delivery_issues(root), [])

    def test_flags_nextjs_project_without_a_homepage_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"next": "16.0.0"}}),
                encoding="utf-8",
            )

            issues = _nextjs_frontend_delivery_issues(root)

            self.assertTrue(issues)
            self.assertIn("no recognized homepage route", issues[0])

    def test_ignores_non_next_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps({"dependencies": {"vite": "7.0.0"}}),
                encoding="utf-8",
            )
            (root / "index.html").write_text(
                "To get started, edit the page.tsx file.", encoding="utf-8"
            )

            self.assertEqual(_nextjs_frontend_delivery_issues(root), [])


if __name__ == "__main__":
    unittest.main()
